/* Seeker 10.3: campaign consequence ledger. Uses the existing Campaign Workspace.
   No GM data is ever requested from player pages. */
(() => {
  'use strict';
  const workspace=document.querySelector('[data-v8-root]');
  const host=document.getElementById('worldConsequenceHost');
  const portal=document.getElementById('worldKnownEvents');
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(url,opt={}) {
    const response=await fetch(url,{cache:'no-store',...opt,headers:{...(opt.body?{'Content-Type':'application/json'}:{}),...(opt.headers||{})}});
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(result.detail||`Request failed (${response.status})`);
    return result;
  }
  const dateText=t=>new Date(Number(t)*1000).toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'});
  const notice=(message,error=false)=>{const e=document.getElementById('worldEventNotice');if(e){e.textContent=message;e.classList.toggle('error',error);e.hidden=false;}else window.SeekerUI?.toast?.(message,{tone:error?'error':'success'});};
  const option=(id,name,selected)=>`<option value="${esc(id)}" ${String(id)===String(selected)?'selected':''}>${esc(name)}</option>`;
  let rows=[],references={sessions:[],entities:[],maps:[]},editing=null;
  function refList(field,value){
    const entries=field==='session_id'?references.sessions:field==='entity_id'?references.entities:field==='marker_id'?(references.maps.find(m=>String(m.id)===String(editing?.map_id))?.markers||[]):references.maps;
    const title=field==='session_id'?'Session':field==='entity_id'?'Campaign object':field==='marker_id'?'Location marker':'Map';
    return `<label>${title}<select name="${field}">${option('','— No '+title.toLowerCase()+' —',value)}${entries.map(x=>option(x.id,x.name||x.title||('Object '+x.id),value)).join('')}</select></label>`;
  }
  function editingForm() {
    const x=editing||{},isPublished=x.status==='published';
    return `<form id="worldEventForm" class="world-event-form">
      <div class="world-fields"><label>GM title<input name="title" maxlength="180" required value="${esc(x.title||'')}" placeholder="The duke disappears"></label>
      <label>Type<select name="kind">${['event','discovery','consequence','travel','quest','relationship'].map(k=>option(k,k[0].toUpperCase()+k.slice(1),x.kind||'event')).join('')}</select></label>
      ${refList('session_id',x.session_id)}${refList('entity_id',x.entity_id)}${refList('map_id',x.map_id)}${refList('marker_id',x.marker_id)}</div>
      <label>GM-only notes<textarea name="gm_notes" maxlength="12000" rows="3" placeholder="What really happened; secrets, consequences and follow-ups">${esc(x.gm_notes||'')}</textarea></label>
      <div class="world-public-fields"><div><strong>Player-facing publication</strong><small>Never copies the GM title or notes automatically. You decide what players can learn.</small></div>
      <label>Safe title<input name="player_title" maxlength="180" value="${esc(x.player_title||'')}" placeholder="News from Sunrock"></label>
      <label>Safe summary<textarea name="player_summary" maxlength="4000" rows="3" placeholder="Only information already known to this party">${esc(x.player_summary||'')}</textarea></label>
      <label>Status<select name="status">${['draft','published','archived'].map(k=>option(k,k[0].toUpperCase()+k.slice(1),x.status||'draft')).join('')}</select></label></div>
      <div class="world-form-actions"><button type="submit" class="v8-button">${editing?'Save changes':'Create event'}</button><button type="button" class="v8-button ghost" id="worldCancel">Cancel</button></div>
    </form>`;
  }
  function displayRow(x){
    return `<article class="world-event-row" data-event-id="${Number(x.id)}">
      <div><div class="world-event-meta"><span class="world-status ${esc(x.status)}">${esc(x.status)}</span><span>${esc(dateText(x.occurred_at))}</span><span>${esc(x.kind)}</span></div>
      <strong>${esc(x.title)}</strong><p>${esc(x.gm_notes||'No GM notes yet.').slice(0,220)}</p>
      <small>${esc([x.session_title,x.entity_name,x.map_name,x.marker_title].filter(Boolean).join(' · ')||'Unlinked world event')}</small></div>
      <button class="v8-button ghost small" data-event-edit="${Number(x.id)}">Edit</button></article>`;
  }
  function render(){
    if(!host)return;
    const draft=rows.filter(e=>e.status==='draft').length,published=rows.filter(e=>e.status==='published').length;
    host.innerHTML=`<section class="v8-panel world-ledger"><header><div><span class="eyebrow">LIVING WORLD · CAMPAIGN CONSEQUENCES</span><h3>What changed in the world?</h3></div><button type="button" class="v8-button small" id="worldAdd">＋ Record event</button></header>
      <p>Link meaningful events to sessions, NPCs and maps. Drafts and private notes stay GM-only. Publication uses separately written player-safe text.</p>
      <div class="world-ledger-summary"><span>${draft} private drafts</span><span>${published} player-visible events</span><span>${rows.length} recorded</span></div>
      <p id="worldEventNotice" role="status" hidden></p>
      <div id="worldEventEditor" ${editing===null?'hidden':''}>${editing===null?'':editingForm()}</div>
      <div class="world-event-list">${rows.map(displayRow).join('')||'<p>No world events yet. Record a session consequence to start building the campaign history.</p>'}</div>
    </section>`;
    host.querySelector('#worldAdd')?.addEventListener('click',()=>{editing={};render();host.querySelector('[name="title"]')?.focus()});
    host.querySelector('#worldCancel')?.addEventListener('click',()=>{editing=null;render()});
    host.querySelectorAll('[data-event-edit]').forEach(button=>button.addEventListener('click',()=>{editing=rows.find(x=>x.id===Number(button.dataset.eventEdit))||{};render();host.querySelector('[name="title"]')?.focus()}));
    host.querySelector('#worldEventForm')?.addEventListener('submit',save);
    host.querySelector('[name="map_id"]')?.addEventListener('change',e=>{
      const id=Number(e.target.value)||null;editing={...editing,...Object.fromEntries(new FormData(host.querySelector('#worldEventForm'))),map_id:id,marker_id:null};
      render();
    });
  }
  async function save(event){
    event.preventDefault();
    const form=event.currentTarget,button=form.querySelector('[type="submit"]');
    const data=Object.fromEntries(new FormData(form));
    for(const k of ['session_id','entity_id','map_id','marker_id'])data[k]=data[k]?Number(data[k]):null;
    const requestedPublication=data.status==='published'&&(editing?.status!=='published'||data.player_title!==(editing?.player_title||'')||data.player_summary!==(editing?.player_summary||''));
    if(requestedPublication){
      if(!data.player_title.trim()||!data.player_summary.trim()){notice('A player-safe title and summary are required.',true);return;}
      if(!confirm('Publish this exact player-facing title and summary to players in this campaign? GM notes remain private.'))return;
      data.confirm_publish=true;
    }
    button.disabled=true;
    try{
      const id=Number(editing?.id)||null;
      if(id)data.expected_updated_at=editing.updated_at;
      await api(id?`/api/world/events/${id}`:'/api/world/events',{method:id?'PUT':'POST',body:JSON.stringify(data)});
      editing=null;await refresh();notice('Campaign event saved.');
    }catch(err){notice(err.message,true);button.disabled=false;}
  }
  async function refresh(){
    if(!host)return;
    try{
      const [result,state]=await Promise.all([api('/api/world/events'),api('/api/v8/state')]);
      rows=result.events||[];
      references={sessions:(state.sessions||[]).map(x=>({...x,name:x.title})),entities:state.entities||[],maps:state.maps||[]};
      render();
    }catch(err){host.innerHTML=`<p role="alert">${esc(err.message)}</p>`;}
  }
  if(workspace&&host){
    let loaded=false;
    document.querySelectorAll('[data-v8-tab="world"]').forEach(button=>button.addEventListener('click',()=>{if(!loaded){loaded=true;refresh()}}));
    if(location.hash.startsWith('#world')){
      refresh().then(()=>{
        const q=new URLSearchParams(location.search);
        const entity=Number(q.get('entity_id'))||null,map=Number(q.get('map_id'))||null,marker=Number(q.get('marker_id'))||null;
        if(entity||map||marker){editing={entity_id:entity,map_id:map,marker_id:marker};render();host.querySelector('[name="title"]')?.focus()}
      });
    }
    document.addEventListener('seeker:event',e=>{if(String(e.detail?.path||'').includes('/api/world/events'))refresh()});
  }
  if(portal){
    api('/api/world/known-events').then(result=>{
      const events=result.events||[];
      portal.innerHTML=events.length?events.slice(0,12).map(e=>`<article class="world-known-event"><small>${esc(dateText(e.occurred_at))} · ${esc(e.kind)}</small><strong>${esc(e.title)}</strong><p>${esc(e.summary)}</p></article>`).join(''):'<p>No newly published world events.</p>';
    }).catch(()=>{portal.textContent='World updates are currently unavailable.'});
  }
})();
