(()=>{
  const root=document.querySelector('[data-foundry-workshop]');
  if(!root) return;
  const stateTag=document.getElementById('foundryWorkshopState');
  const initial=stateTag ? JSON.parse(stateTag.textContent||'{}') : {};
  const state={actors:initial.actors||[], entries:initial.prepared_content||[], commands:initial.commands||[]};
  const form=document.getElementById('foundryWorkshopForm');
  const list=document.getElementById('foundryPrepList');
  const log=document.getElementById('foundryCommandLog');
  const title=document.getElementById('fwFormTitle');
  const $=s=>document.querySelector(s);
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const jsonFetch=async(url,opts={})=>{const r=await fetch(url,opts);const b=await r.json().catch(()=>({}));if(!r.ok) throw Error(b.detail||'Request failed');return b;};
  const send=(url,method,data)=>jsonFetch(url,{method,headers:{'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});
  const toast=(msg,bad=false)=>{const n=document.createElement('div');n.className=`v6-toast${bad?' bad':''}`;n.textContent=msg;document.body.appendChild(n);requestAnimationFrame(()=>n.classList.add('show'));setTimeout(()=>{n.classList.remove('show');setTimeout(()=>n.remove(),220)},2200)};
  const pillList=txt=>String(txt||'').split(',').map(v=>v.trim()).filter(Boolean);
  const actorOptions=()=>(state.actors||[]).map(a=>`<option value="${esc(a.actor_id)}">${esc(a.name||'Unnamed actor')}</option>`).join('');
  const kindLabel=k=>({item:'Item',feat:'Feat',monster:'Monster',npc:'NPC',homebrew:'Homebrew'}[k]||k||'Entry');
  function renderLog(){
    const rows=state.commands||[];
    log.innerHTML=rows.length?rows.map(r=>`<article class="command-log-item"><span class="status ${esc(r.status||'queued')}">${esc(r.status||'queued')}</span><strong>${esc(r.command_type||'action')}</strong><small>${esc(r.requested_by||'Unknown')} · ${esc((r.actor_id||'world').slice(0,80))}</small>${r.result?.message?`<div>${esc(r.result.message)}</div>`:''}</article>`).join(''):'<p class="muted">No bridge actions yet.</p>';
  }
  function renderList(){
    const rows=state.entries||[];
    list.innerHTML=rows.length?rows.map(entry=>{
      const p=entry.payload||{};
      const tags=pillList(entry.tags||p.traits||'');
      const actorOnly=['item','feat','homebrew'].includes(String(entry.kind||''));
      return `<article class="foundry-prep-entry" data-entry-id="${entry.id}">
        <header>
          <div>
            <div class="foundry-prep-meta"><span>${esc(kindLabel(entry.kind))}</span><span>${esc(entry.target_type||'world')}</span>${tags.slice(0,3).map(t=>`<span>${esc(t)}</span>`).join('')}</div>
            <h3>${esc(entry.title||'Untitled')}</h3>
            ${entry.subtitle?`<small>${esc(entry.subtitle)}</small>`:''}
          </div>
          <button class="quiet-btn" type="button" data-fw-edit="${entry.id}">Edit</button>
        </header>
        ${entry.summary?`<p>${esc(entry.summary)}</p>`:''}
        <div class="foundry-prep-actions">
          <button class="quiet-btn" type="button" data-fw-push-world="${entry.id}">Push to world</button>
          ${actorOnly?`<select data-fw-actor><option value="">Choose actor…</option>${actorOptions()}</select><button class="quiet-btn" type="button" data-fw-push-actor="${entry.id}">Give to actor</button>`:''}
          <button class="quiet-btn" type="button" data-fw-delete="${entry.id}">Delete</button>
        </div>
      </article>`;
    }).join(''):'<div class="foundry-empty">No prepared Foundry content yet.</div>';
  }
  function fillForm(entry){
    form.reset();
    title.textContent=entry ? `Edit ${entry.title}` : 'New prep entry';
    form.elements.id.value=entry?.id||'';
    form.elements.kind.value=entry?.kind||'item';
    form.elements.target_type.value=entry?.target_type||'world';
    form.elements.title.value=entry?.title||'';
    form.elements.subtitle.value=entry?.subtitle||'';
    form.elements.summary.value=entry?.summary||'';
    form.elements.tags.value=entry?.tags||'';
    const p=entry?.payload||{};
    ['img','item_type','level','quantity','price','traits','rarity','description','actor_role','perception','ac','hp','speed','languages','str_mod','dex_mod','con_mod','int_mod','wis_mod','cha_mod']
      .forEach(k=>{ if(form.elements[k]) form.elements[k].value = p[k] ?? ''; });
  }
  async function refresh(){
    const data=await jsonFetch('/api/v61/foundry/workshop');
    state.actors=data.actors||[]; state.entries=data.prepared_content||[]; state.commands=data.commands||[];
    renderList(); renderLog();
  }
  form.addEventListener('submit',async e=>{
    e.preventDefault();
    const fd=new FormData(form);
    const payload={
      id:fd.get('id')||undefined,
      kind:fd.get('kind'), target_type:fd.get('target_type'), title:fd.get('title'), subtitle:fd.get('subtitle'),
      summary:fd.get('summary'), tags:fd.get('tags'),
      payload:{ img:fd.get('img'), item_type:fd.get('item_type'), level:fd.get('level'), quantity:fd.get('quantity'), price:fd.get('price'), traits:fd.get('traits'), rarity:fd.get('rarity'), description:fd.get('description'), actor_role:fd.get('actor_role'), perception:fd.get('perception'), ac:fd.get('ac'), hp:fd.get('hp'), speed:fd.get('speed'), languages:fd.get('languages'), str_mod:fd.get('str_mod'), dex_mod:fd.get('dex_mod'), con_mod:fd.get('con_mod'), int_mod:fd.get('int_mod'), wis_mod:fd.get('wis_mod'), cha_mod:fd.get('cha_mod') }
    };
    try{ await send('/api/v61/foundry/content','POST',payload); toast('Prep entry saved.'); fillForm(); await refresh(); }
    catch(err){ toast(err.message||'Could not save the entry.',true); }
  });
  list.addEventListener('click',async e=>{
    const edit=e.target.closest('[data-fw-edit]');
    if(edit){ const entry=state.entries.find(x=>String(x.id)===String(edit.dataset.fwEdit)); if(entry) fillForm(entry); return; }
    const del=e.target.closest('[data-fw-delete]');
    if(del){ if(!confirm('Delete this prepared entry?')) return; try{ await fetch(`/api/v61/foundry/content/${del.dataset.fwDelete}`,{method:'DELETE'}); toast('Deleted.'); await refresh(); }catch(err){ toast('Could not delete the entry.',true);} return; }
    const world=e.target.closest('[data-fw-push-world]');
    if(world){ try{ await send(`/api/v61/foundry/content/${world.dataset.fwPushWorld}/push`,'POST',{target_type:'world'}); toast('Queued for Foundry.'); await refresh(); }catch(err){ toast(err.message||'Could not queue this push.',true);} return; }
    const actor=e.target.closest('[data-fw-push-actor]');
    if(actor){ const card=actor.closest('.foundry-prep-entry'); const select=card?.querySelector('[data-fw-actor]'); const actorId=select?.value; if(!actorId){ toast('Choose an actor first.',true); return; } try{ await send(`/api/v61/foundry/content/${actor.dataset.fwPushActor}/push`,'POST',{target_type:'actor',actor_id:actorId}); toast('Item queued for actor.'); await refresh(); }catch(err){ toast(err.message||'Could not queue this actor push.',true);} }
  });
  $('[data-fw-new]')?.addEventListener('click',()=>fillForm());
  $('[data-fw-reset]')?.addEventListener('click',()=>fillForm());
  fillForm(); renderList(); renderLog();
})();
