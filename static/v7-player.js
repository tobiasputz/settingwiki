(()=>{
  const root=document.querySelector('[data-v7-player-app]');if(!root)return;
  const $=(s,p=document)=>p.querySelector(s),$$=(s,p=document)=>[...p.querySelectorAll(s)];
  const charId=root.dataset.characterId;
  const toast=(msg,bad=false)=>{const n=document.createElement('div');n.className=`v6-toast${bad?' bad':''}`;n.textContent=msg;document.body.appendChild(n);requestAnimationFrame(()=>n.classList.add('show'));setTimeout(()=>{n.classList.remove('show');setTimeout(()=>n.remove(),250)},2400)};
  const send=async(url,body)=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(b.detail||'Request failed');return b};
  function tab(name){$$('[data-player-tab]').forEach(b=>b.classList.toggle('active',b.dataset.playerTab===name));$$('[data-player-pane]').forEach(p=>p.classList.toggle('active',p.dataset.playerPane===name));history.replaceState(null,'',`#${name}`);scrollTo({top:0,behavior:'instant'})}
  $$('[data-player-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.playerTab));const h=location.hash.slice(1);if($(`[data-player-tab="${CSS.escape(h)}"]`))tab(h);
  $('[data-character-switch]')?.addEventListener('change',e=>location.href=`/app?character_id=${encodeURIComponent(e.currentTarget.value)}${location.hash}`);
  const live=charId&&window.SeekerFoundryLive?new window.SeekerFoundryLive.FoundryLiveState(root,charId):null;
  const statusToast=(row,status)=>{const label=row.delivery_label||status;if(status==='failed')toast(label,true);else if(['queued','dispatched','executing'].includes(status))toast(`${label}…`)};
  async function actorAction(payload,button){
    if(!charId)return;
    const delta=Number(payload.delta||0);const op=payload.action==='adjust_resource'?live?.beginResource(payload.resource,delta):payload.action==='adjust_item_quantity'?live?.beginItem(payload.item_id,delta):null;
    button.dataset.busy='1';button.setAttribute('aria-busy','true');
    try{
      const queued=await send(`/api/v61/characters/${charId}/foundry/action`,payload);const id=queued?.command?.id;
      if(!id)throw Error('Seeker did not create a Foundry delivery record.');
      const result=await window.SeekerFoundryLive.waitForCommand(id,{onStatus:statusToast,timeout:45000});
      if(!result){live?.rollback(op);toast('Foundry is not responding yet. The action remains queued; the display will update when it is applied.',true);return}
      live?.commit(op,result.result?.after);
      try{await live?.refresh()}catch(_){/* ACK projection already keeps the visible value authoritative. */}
      toast(result.result?.message||'Applied in Foundry.');
    }catch(err){live?.rollback(op);toast(err.message,true)}finally{delete button.dataset.busy;button.removeAttribute('aria-busy')}
  }
  $$('[data-player-resource]').forEach(b=>b.onclick=()=>actorAction({action:'adjust_resource',resource:b.dataset.playerResource,delta:Number(b.dataset.delta)},b));
  $$('[data-player-set-resource]').forEach(f=>f.addEventListener('submit',e=>{e.preventDefault();const input=f.querySelector('input[type=number]'),button=f.querySelector('button[type=submit]'),value=Number.parseInt(input?.value||'',10);if(!Number.isFinite(value))return toast('Enter a whole-number value.',true);actorAction({action:'set_resource',resource:f.dataset.playerSetResource,value},button)}));
  $$('[data-player-item]').forEach(b=>b.onclick=()=>actorAction({action:'adjust_item_quantity',item_id:b.dataset.playerItem,delta:Number(b.dataset.delta)},b));
  if(live){let refreshing=false;const refreshLive=async()=>{if(refreshing||document.hidden)return;refreshing=true;try{await live.refresh()}catch(_){/* transient bridge/network failures should not interrupt table play */}finally{refreshing=false}};window.addEventListener('focus',refreshLive);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshLive()});setInterval(refreshLive,2500)}
  $$('[data-claim-loot]').forEach(b=>b.onclick=async()=>{if(!charId)return;const old=b.textContent;b.disabled=true;b.textContent='Claiming…';try{await send(`/api/v7/loot/items/${b.dataset.claimLoot}/claim`,{character_id:Number(charId),quantity:1});toast('Claimed. Foundry will receive it if linked.');setTimeout(()=>location.reload(),900)}catch(err){toast(err.message,true);b.disabled=false;b.textContent=old}});
  $('[data-player-entity-search]')?.addEventListener('input',e=>{const q=e.currentTarget.value.trim().toLowerCase();$$('[data-player-entity]').forEach(a=>a.hidden=q&&!String(a.dataset.search||'').includes(q))});
})();
