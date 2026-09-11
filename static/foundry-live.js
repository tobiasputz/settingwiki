(()=>{
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const int=(v,f=0)=>{const n=Number.parseInt(v,10);return Number.isFinite(n)?n:f};
  class FoundryLiveState{
    constructor(root,characterId){
      this.root=root||document;this.characterId=String(characterId||'');this.resources=new Map();this.items=new Map();this.seq=0;
      this.scan();
      this.channel=null;
      try{if('BroadcastChannel' in window){this.channel=new BroadcastChannel('seeker-foundry-live');this.channel.addEventListener('message',e=>{if(String(e.data?.characterId||'')===this.characterId)this.refresh().catch(()=>{})})}}catch(_){this.channel=null}
    }
    scan(){
      this.root.querySelectorAll('[data-resource-value]').forEach(el=>{
        const key=el.dataset.resourceValue;if(!key)return;
        const max=int(el.dataset.max,999999),current=int(el.dataset.current,int(el.textContent,0));
        const row=this.resources.get(key)||{confirmed:current,max,pending:new Map()};
        row.confirmed=current;row.max=max||999999;row.el=el;row.card=this.root.querySelector(`[data-resource-card="${CSS.escape(key)}"]`);row.mark=this.root.querySelector(`[data-resource-sync="${CSS.escape(key)}"]`);this.resources.set(key,row);
      });
      this.root.querySelectorAll('[data-resource-mini]').forEach(el=>{
        const key=el.dataset.resourceMini;if(!key)return;
        const current=int(el.dataset.current,int(el.textContent,0)),max=int(el.dataset.max,999999);
        const row=this.resources.get(key)||{confirmed:current,max:max||999999,pending:new Map()};row.confirmed=current;row.max=max||999999;row.el=el;row.mini=true;this.resources.set(key,row);
      });
      this.root.querySelectorAll('[data-item-quantity]').forEach(el=>{const id=el.dataset.itemQuantity;if(!id)return;const current=int(el.dataset.current,int(String(el.textContent).replace(/\D/g,''),0));this.items.set(id,{confirmed:current,pending:new Map(),el})});
    }
    _visible(row){return clamp(row.confirmed+[...row.pending.values()].reduce((a,b)=>a+b,0),0,row.max||999999)}
    _renderResource(key){const row=this.resources.get(key);if(!row||!row.el)return;const value=this._visible(row);row.el.dataset.current=String(value);row.el.textContent=String(value);if(key==='temp_hp'){const temp=this.root.querySelector('[data-resource-temp]');if(temp){temp.hidden=value<=0;temp.textContent=value>0?`+${value} temp`:''}}const pending=row.pending.size>0;row.card?.classList.toggle('is-syncing',pending);row.mark?.classList.toggle('pending',pending);row.mark?.setAttribute('title',pending?'Waiting for Foundry confirmation':'Synced')}
    _renderItem(id){const row=this.items.get(id);if(!row||!row.el)return;const value=Math.max(0,row.confirmed+[...row.pending.values()].reduce((a,b)=>a+b,0));row.el.dataset.current=String(value);const prefix=row.el.closest('.foundry-item-grid')?'×':'';row.el.textContent=prefix?`${value!==1?`×${value} · `:''}`:String(value);row.el.closest('article,details')?.classList.toggle('is-syncing',row.pending.size>0)}
    beginResource(key,delta){const row=this.resources.get(key);if(!row)return null;const token=`r${++this.seq}`;row.pending.set(token,int(delta));this._renderResource(key);return {kind:'resource',key,token}}
    beginItem(id,delta){const row=this.items.get(String(id));if(!row)return null;const token=`i${++this.seq}`;row.pending.set(token,int(delta));this._renderItem(String(id));return {kind:'item',key:String(id),token}}
    commit(op,after){if(!op){this.notify();return}const map=op.kind==='item'?this.items:this.resources,row=map.get(op.key);if(!row){this.notify();return}row.pending.delete(op.token);if(Number.isFinite(Number(after)))row.confirmed=Math.max(0,int(after));op.kind==='item'?this._renderItem(op.key):this._renderResource(op.key);this.notify()}
    notify(){try{this.channel?.postMessage({characterId:this.characterId,at:Date.now()})}catch(_){}}
    rollback(op){if(!op)return;const map=op.kind==='item'?this.items:this.resources,row=map.get(op.key);if(!row)return;row.pending.delete(op.token);op.kind==='item'?this._renderItem(op.key):this._renderResource(op.key)}
    applySheet(sheet={}){
      const v=sheet.vitals||{};const values={hp:v.hp?.value,temp_hp:v.hp?.temp,hero_points:v.hero_points?.value,focus:v.focus?.value};
      for(const [key,val] of Object.entries(values)){const row=this.resources.get(key);if(row&&val!==undefined&&val!==null){row.confirmed=Math.max(0,int(val));this._renderResource(key)}}
      for(const item of sheet.inventory||[]){const id=String(item?.id||'');const row=this.items.get(id);if(row&&item?.quantity!==undefined){row.confirmed=Math.max(0,int(item.quantity));this._renderItem(id)}}
      const received=document.querySelector('[data-foundry-received-at]');if(received&&sheet)received.dataset.foundryReceivedAt=String(Date.now()/1000);
    }
    async refresh(){if(!this.characterId)return null;const r=await fetch(`/api/v61/characters/${encodeURIComponent(this.characterId)}/foundry-state`,{cache:'no-store'});const body=await r.json().catch(()=>({}));if(!r.ok)throw Error(body.detail||'Could not refresh Foundry state.');this.applySheet(body.sheet||{});return body}
  }
  async function waitForCommand(id,{onStatus,timeout=45000}={}){
    const deadline=Date.now()+timeout;let last='';
    while(Date.now()<deadline){
      const r=await fetch(`/api/v6/foundry/commands/${encodeURIComponent(id)}`,{cache:'no-store'});const row=await r.json().catch(()=>({}));if(!r.ok)throw Error(row.detail||'Could not read Foundry delivery state.');
      const status=String(row.status||'queued');if(status!==last){last=status;onStatus?.(row,status)}
      if(status==='done')return row;if(status==='failed'||status==='cancelled')throw Object.assign(Error(row.last_error||row.result?.message||'Foundry rejected the action.'),{row});
      await new Promise(resolve=>setTimeout(resolve,650));
    }
    return null;
  }
  window.SeekerFoundryLive={FoundryLiveState,waitForCommand};
})();
