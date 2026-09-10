(()=>{
  const root=document.querySelector('[data-v7-player-app]');if(!root)return;
  const $=(s,p=document)=>p.querySelector(s),$$=(s,p=document)=>[...p.querySelectorAll(s)];
  const charId=root.dataset.characterId;
  const toast=(msg,bad=false)=>{const n=document.createElement('div');n.className=`v6-toast${bad?' bad':''}`;n.textContent=msg;document.body.appendChild(n);requestAnimationFrame(()=>n.classList.add('show'));setTimeout(()=>{n.classList.remove('show');setTimeout(()=>n.remove(),250)},2400)};
  const send=async(url,body)=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(b.detail||'Request failed');return b};
  function tab(name){$$('[data-player-tab]').forEach(b=>b.classList.toggle('active',b.dataset.playerTab===name));$$('[data-player-pane]').forEach(p=>p.classList.toggle('active',p.dataset.playerPane===name));history.replaceState(null,'',`#${name}`);scrollTo({top:0,behavior:'instant'})}
  $$('[data-player-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.playerTab));const h=location.hash.slice(1);if($(`[data-player-tab="${CSS.escape(h)}"]`))tab(h);
  $('[data-character-switch]')?.addEventListener('change',e=>location.href=`/app?character_id=${encodeURIComponent(e.currentTarget.value)}${location.hash}`);
  async function waitForFoundryCommand(id){
    const deadline=Date.now()+18000;let last='';
    while(Date.now()<deadline){
      const r=await fetch(`/api/v6/foundry/commands/${encodeURIComponent(id)}`,{cache:'no-store'});
      const row=await r.json().catch(()=>({}));if(!r.ok)throw Error(row.detail||'Could not read Foundry delivery state.');
      const status=String(row.status||'queued');
      if(status!==last){last=status;const label=row.delivery_label||status;toast(`${label}${['queued','dispatched','executing'].includes(status)?'…':''}`,status==='failed')}
      if(status==='done')return row;
      if(status==='failed'||status==='cancelled')throw Error(row.last_error||row.result?.message||'Foundry rejected the action.');
      await new Promise(r=>setTimeout(r,700));
    }
    return null;
  }
  async function actorAction(payload,button){
    if(!charId)return;button.disabled=true;
    try{
      const queued=await send(`/api/v61/characters/${charId}/foundry/action`,payload);const id=queued?.command?.id;
      if(!id)throw Error('Seeker did not create a Foundry delivery record.');
      toast('Waiting for Foundry…');
      const result=await waitForFoundryCommand(id);
      if(result){toast(result.result?.message||'Applied in Foundry.');setTimeout(()=>location.reload(),350)}
      else toast('Still waiting. The action remains safely queued and will not disappear.',true);
    }catch(err){toast(err.message,true)}finally{button.disabled=false}
  }
  $$('[data-player-resource]').forEach(b=>b.onclick=()=>actorAction({action:'adjust_resource',resource:b.dataset.playerResource,delta:Number(b.dataset.delta)},b));
  $$('[data-player-item]').forEach(b=>b.onclick=()=>actorAction({action:'adjust_item_quantity',item_id:b.dataset.playerItem,delta:Number(b.dataset.delta)},b));
  $$('[data-claim-loot]').forEach(b=>b.onclick=async()=>{if(!charId)return;const old=b.textContent;b.disabled=true;b.textContent='Claiming…';try{await send(`/api/v7/loot/items/${b.dataset.claimLoot}/claim`,{character_id:Number(charId),quantity:1});toast('Claimed. Foundry will receive it if linked.');setTimeout(()=>location.reload(),900)}catch(err){toast(err.message,true);b.disabled=false;b.textContent=old}});
  $('[data-player-entity-search]')?.addEventListener('input',e=>{const q=e.currentTarget.value.trim().toLowerCase();$$('[data-player-entity]').forEach(a=>a.hidden=q&&!String(a.dataset.search||'').includes(q))});
})();
