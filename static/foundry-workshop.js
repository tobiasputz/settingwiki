(()=>{
  const root=document.querySelector('[data-foundry-workshop]');
  if(!root) return;
  const initial=(()=>{try{return JSON.parse(document.getElementById('foundryWorkshopState')?.textContent||'{}')}catch{return {}}})();
  const state={actors:initial.actors||[],entries:initial.prepared_content||[],commands:initial.commands||[],filter:'all',query:'',attacks:[],abilities:[],savedSnapshot:'',currentId:null};
  const form=document.getElementById('foundryWorkshopForm');
  const list=document.getElementById('foundryPrepList');
  const log=document.getElementById('foundryCommandLog');
  const preview=document.getElementById('foundryLivePreview');
  const saveState=document.querySelector('[data-fw-save-state]');
  const toolbarTitle=document.getElementById('fwToolbarTitle');
  const editingLabel=document.getElementById('fwEditingLabel');
  const $=(s,p=document)=>p.querySelector(s), $$=(s,p=document)=>[...p.querySelectorAll(s)];
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const lines=s=>esc(s).replace(/\n/g,'<br>');
  const slugList=s=>String(s||'').split(',').map(v=>v.trim()).filter(Boolean);
  const num=(v,f='—')=>String(v??'').trim()===''?f:String(v);
  const signed=v=>{const s=String(v??'').trim();if(!s)return '—';const n=Number(s);return Number.isFinite(n)?`${n>=0?'+':''}${n}`:esc(s)};
  const kindName=k=>({monster:'Creature',npc:'NPC',item:'Item',feat:'Feat',homebrew:'Freeform'}[k]||'Homebrew');
  const kindIcon=k=>({monster:'♜',npc:'♟',item:'◇',feat:'✦',homebrew:'⌘'}[k]||'◇');
  const creatureKind=k=>k==='monster'||k==='npc';
  const jsonFetch=async(url,opts={})=>{const r=await fetch(url,opts),b=await r.json().catch(()=>({}));if(!r.ok)throw Error(b.detail||'Request failed');return b};
  const send=(url,method,data)=>jsonFetch(url,{method,headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
  const toast=(msg,bad=false)=>{const n=document.createElement('div');n.className=`v6-toast${bad?' bad':''}`;n.textContent=msg;document.body.appendChild(n);requestAnimationFrame(()=>n.classList.add('show'));setTimeout(()=>{n.classList.remove('show');setTimeout(()=>n.remove(),240)},2400)};
  const field=n=>form.elements[n];
  const fieldValue=n=>field(n)?.value??'';
  const setField=(n,v)=>{if(field(n))field(n).value=v??''};
  const actionGlyph=v=>v==='reaction'?'↺':v==='free'?'◇':v==='1'?'◆':v==='2'?'◆◆':v==='3'?'◆◆◆':'';

  function setDirty(){
    const snapshot=JSON.stringify(collectData(false));
    const dirty=snapshot!==state.savedSnapshot;
    saveState?.classList.toggle('dirty',dirty);saveState?.classList.toggle('saved',!dirty&&!!state.currentId);
    if(saveState){$('strong',saveState).textContent=dirty?'Unsaved changes':(state.currentId?'Saved':'Not saved yet')}
    try{localStorage.setItem('seeker-foundry-workshop-draft',snapshot)}catch{}
  }
  function setKind(kind,{resetCollections=false}={}){
    const k=['monster','npc','item','feat','homebrew'].includes(kind)?kind:'monster';
    setField('kind',k);
    $$('[data-fw-kind]').forEach(b=>b.classList.toggle('active',b.dataset.fwKind===k));
    $$('[data-fw-show]').forEach(el=>{const token=el.dataset.fwShow;const visible=token==='creature'?creatureKind(k):token===k;el.classList.toggle('fw-hidden',!visible)});
    $$('[data-fw-section]').forEach(el=>{const token=el.dataset.fwSection;const visible=token==='creature'?creatureKind(k):token===k;el.classList.toggle('fw-hidden',!visible)});
    const give=$('[data-fw-push-actor]'), target=$('.fw-actor-target');
    const canGive=!creatureKind(k) && (k==='item'||k==='feat'||k==='homebrew');
    if(give){give.disabled=!canGive;give.title=canGive?'Save and add this item/feat to the selected actor':'Creatures and NPCs are created in the Foundry world directory'}
    target?.classList.toggle('fw-disabled',!canGive);
    $$('[data-fw-template]').forEach(b=>b.classList.toggle('visible',b.dataset.fwTemplateKind===k));
    if(resetCollections){state.attacks=[];state.abilities=[];renderRepeaters()}
    editingLabel.textContent=`${state.currentId?'EDITING':'NEW'} ${kindName(k).toUpperCase()}`;
    updateToolbar();renderPreview();setDirty();
  }
  function updateToolbar(){toolbarTitle.textContent=fieldValue('title').trim()||`Untitled ${kindName(fieldValue('kind')).toLowerCase()}`}

  function attackRow(row={},index=0){
    return `<div class="fw-repeat-row" data-attack-index="${index}">
      <label><span>Name</span><input data-rkey="name" value="${esc(row.name||'')}" placeholder="Claw"></label>
      <label><span>Type</span><select data-rkey="type"><option value="melee" ${row.type!=='ranged'?'selected':''}>Melee</option><option value="ranged" ${row.type==='ranged'?'selected':''}>Ranged</option></select></label>
      <label><span>Bonus</span><input data-rkey="bonus" type="number" step="1" value="${esc(row.bonus??'')}" placeholder="12"></label>
      <label><span>Damage</span><input data-rkey="damage" value="${esc(row.damage||'')}" placeholder="2d8+4 slashing"></label>
      <button class="fw-remove-row" type="button" data-remove-attack="${index}" title="Remove strike">×</button>
      <label class="fw-repeat-traits"><span>Traits / extra text</span><input data-rkey="traits" value="${esc(row.traits||'')}" placeholder="agile, finesse; plus 1d6 fire"></label>
    </div>`;
  }
  function abilityRow(row={},index=0){
    return `<div class="fw-repeat-row ability" data-ability-index="${index}">
      <label><span>Ability name</span><input data-rkey="name" value="${esc(row.name||'')}" placeholder="Cinder Step"></label>
      <label><span>Actions</span><select data-rkey="actions"><option value="" ${!row.actions?'selected':''}>Passive</option><option value="1" ${row.actions==='1'?'selected':''}>◆ 1 action</option><option value="2" ${row.actions==='2'?'selected':''}>◆◆ 2 actions</option><option value="3" ${row.actions==='3'?'selected':''}>◆◆◆ 3 actions</option><option value="reaction" ${row.actions==='reaction'?'selected':''}>↺ Reaction</option><option value="free" ${row.actions==='free'?'selected':''}>◇ Free</option></select></label>
      <label><span>Traits</span><input data-rkey="traits" value="${esc(row.traits||'')}" placeholder="fire, concentrate"></label>
      <button class="fw-remove-row" type="button" data-remove-ability="${index}" title="Remove ability">×</button>
      <textarea data-rkey="description" placeholder="Ability rules text…">${esc(row.description||'')}</textarea>
    </div>`;
  }
  function renderRepeaters(){
    const a=$('[data-fw-attacks]'),b=$('[data-fw-abilities]');
    if(a)a.innerHTML=state.attacks.length?state.attacks.map(attackRow).join(''):'<div class="fw-repeater-empty">No strikes yet. Add only the attacks you expect to use.</div>';
    if(b)b.innerHTML=state.abilities.length?state.abilities.map(abilityRow).join(''):'<div class="fw-repeater-empty">No special abilities yet. Add reactions, passive abilities, activated powers, or signature tricks here.</div>';
  }
  function syncRepeaters(){
    $$('[data-attack-index]').forEach(row=>{const i=+row.dataset.attackIndex;state.attacks[i] ||= {};$$('[data-rkey]',row).forEach(el=>state.attacks[i][el.dataset.rkey]=el.value)});
    $$('[data-ability-index]').forEach(row=>{const i=+row.dataset.abilityIndex;state.abilities[i] ||= {};$$('[data-rkey]',row).forEach(el=>state.abilities[i][el.dataset.rkey]=el.value)});
  }

  const payloadFields=['img','level','rarity','size','actor_role','traits','item_type','feat_category','homebrew_document','price','bulk','usage','hands','quantity','item_category','action_cost','frequency','prerequisites','trigger','requirements','activation_actions','activation_frequency','activation_trigger','activation_requirements','homebrew_actions','homebrew_frequency','homebrew_trigger','perception','speed','senses','languages','skills','ac','fortitude','reflex','will','hp','immunities','weaknesses','resistances','str_mod','dex_mod','con_mod','int_mod','wis_mod','cha_mod','description','spellcasting','gm_notes'];
  function collectData(sync=true){
    if(sync)syncRepeaters();
    const kind=fieldValue('kind')||'monster';
    const payload={};payloadFields.forEach(k=>payload[k]=fieldValue(k));payload.attacks=state.attacks;payload.abilities=state.abilities;
    return {id:fieldValue('id')||undefined,kind,target_type:'world',title:fieldValue('title').trim(),subtitle:fieldValue('subtitle').trim(),summary:fieldValue('summary'),tags:fieldValue('traits'),payload};
  }
  function fillForm(entry=null){
    form.reset();state.currentId=entry?.id||null;state.attacks=[];state.abilities=[];
    setField('id',entry?.id||'');setField('title',entry?.title||'');setField('subtitle',entry?.subtitle||'');setField('summary',entry?.summary||'');
    const p=entry?.payload||{};payloadFields.forEach(k=>setField(k,p[k]??''));
    if(!entry){setField('level','1');setField('rarity','common');setField('size','med');setField('quantity','1');['str_mod','dex_mod','con_mod','int_mod','wis_mod','cha_mod'].forEach(k=>setField(k,'0'))}
    state.attacks=Array.isArray(p.attacks)?structuredClone(p.attacks):[];state.abilities=Array.isArray(p.abilities)?structuredClone(p.abilities):[];
    setKind(entry?.kind||'monster');renderRepeaters();updateToolbar();renderPreview();
    state.savedSnapshot=JSON.stringify(collectData());
    setDirty();
    $('[data-fw-duplicate]').disabled=!entry;
    renderLibrary();
    document.querySelector('.fw-form-scroll')?.scrollTo({top:0,behavior:'smooth'});
  }

  function libraryMeta(e){const p=e.payload||{};const lv=String(p.level??'').trim();return [kindName(e.kind),lv!==''?`Level ${lv}`:'',p.rarity&&p.rarity!=='common'?p.rarity:''].filter(Boolean)}
  function renderLibrary(){
    const q=state.query.trim().toLowerCase();
    const rows=state.entries.filter(e=>(state.filter==='all'||e.kind===state.filter)&&(!q||`${e.title} ${e.subtitle} ${e.tags} ${e.kind}`.toLowerCase().includes(q)));
    list.innerHTML=rows.length?rows.map(e=>`<button class="fw-library-entry ${String(e.id)===String(state.currentId)?'active':''}" type="button" data-fw-open="${e.id}"><span class="fw-library-entry-icon">${kindIcon(e.kind)}</span><span><strong>${esc(e.title||'Untitled')}</strong><small>${esc(e.subtitle||kindName(e.kind))}</small><span class="fw-library-entry-meta">${libraryMeta(e).map(m=>`<span>${esc(m)}</span>`).join('')}</span></span></button>`).join(''):'<div class="fw-library-empty">Nothing matches this view yet.<br>Create something worth surprising your players with.</div>';
  }
  function renderLog(){
    const rows=state.commands||[];
    log.innerHTML=rows.length?rows.slice(0,15).map(r=>`<article class="command-log-item"><span class="status ${esc(r.status||'queued')}">${esc(r.status||'queued')}</span><strong>${esc(String(r.command_type||'action').replaceAll('_',' '))}</strong><small>${esc(r.requested_by||'GM')} · ${esc(r.actor_id||'world')}</small>${r.result?.message?`<div>${esc(r.result.message)}</div>`:''}</article>`).join(''):'<p class="muted">No bridge actions yet.</p>';
  }

  function traitHtml(kind,p){const rarity=String(p.rarity||'common');const raw=[rarity!=='common'?rarity:'',creatureKind(kind)?p.size:'',...slugList(p.traits)].filter(Boolean);return raw.length?`<div class="fw-preview-traits ${kind==='item'?'fw-item-traits':kind==='feat'?'fw-feat-traits':kind==='homebrew'?'fw-free-traits':''}">${raw.map((t,i)=>`<span class="${i===0&&rarity!=='common'?`rarity-${esc(rarity)}`:''}">${esc(t)}</span>`).join('')}</div>`:''}
  function abilityPreview(rows){return (rows||[]).filter(a=>a.name||a.description).map(a=>`<div class="fw-stat-action"><h4>${esc(a.name||'Ability')} ${a.actions?`<span class="fw-action-glyphs">${actionGlyph(a.actions)}</span>`:''}</h4>${a.traits?`<small>${esc(a.traits)}</small>`:''}${a.description?`<p>${lines(a.description)}</p>`:''}</div>`).join('')}
  function creaturePreview(d){const p=d.payload||{},kind=d.kind;const abs=[['STR',p.str_mod],['DEX',p.dex_mod],['CON',p.con_mod],['INT',p.int_mod],['WIS',p.wis_mod],['CHA',p.cha_mod]];
    const defenses=[`<strong>AC</strong> ${num(p.ac)}`,`<strong>Fort</strong> ${signed(p.fortitude)}`,`<strong>Ref</strong> ${signed(p.reflex)}`,`<strong>Will</strong> ${signed(p.will)}`].join('; ');
    const extras=[p.immunities?`<strong>Immunities</strong> ${esc(p.immunities)}`:'',p.weaknesses?`<strong>Weaknesses</strong> ${esc(p.weaknesses)}`:'',p.resistances?`<strong>Resistances</strong> ${esc(p.resistances)}`:''].filter(Boolean).join('; ');
    const attacks=(p.attacks||[]).filter(x=>x.name||x.damage).map(a=>`<p class="fw-stat-strike"><strong>${a.type==='ranged'?'Ranged':'Melee'}</strong> ${esc(a.name||'Strike')} ${signed(a.bonus)}${a.traits?` (${esc(a.traits)})`:''}, <strong>Damage</strong> ${esc(a.damage||'—')}</p>`).join('');
    return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top"><h3>${esc(d.title||'Untitled creature')}</h3><span class="fw-stat-level">${kind==='npc'?'NPC':'CREATURE'} ${esc(num(p.level,'1'))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml(kind,p)}<div class="fw-stat-body">
      <p><strong>Perception</strong> ${signed(p.perception)}${p.senses?`; ${esc(p.senses)}`:''}</p>${p.languages?`<p><strong>Languages</strong> ${esc(p.languages)}</p>`:''}${p.skills?`<p><strong>Skills</strong> ${esc(p.skills)}</p>`:''}
      <div class="fw-stat-abilities">${abs.map(([a,v])=>`<span><strong>${a}</strong> ${signed(v)}</span>`).join('')}</div><hr class="fw-stat-divider">
      <p>${defenses}</p><p><strong>HP</strong> ${num(p.hp)}${extras?`; ${extras}`:''}</p><hr class="fw-stat-divider">
      <p><strong>Speed</strong> ${num(p.speed,'25')} feet</p>${attacks}${p.description?`<div class="fw-stat-action"><p class="fw-stat-desc">${lines(p.description)}</p></div>`:''}${abilityPreview(p.abilities)}${p.spellcasting?`<div class="fw-stat-action"><h4>Spellcasting</h4><p>${lines(p.spellcasting)}</p></div>`:''}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`;
  }
  function itemPreview(d){const p=d.payload||{},act=actionGlyph(p.activation_actions);return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top fw-item-top"><h3>${esc(d.title||'Untitled item')}</h3><span class="fw-stat-level">ITEM ${esc(num(p.level,'0'))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml('item',p)}<div class="fw-stat-body">${p.price?`<p><strong>Price</strong> ${esc(p.price)}</p>`:''}<p><strong>Usage</strong> ${esc(p.usage||'—')}${p.hands?`; <strong>Hands</strong> ${esc(p.hands)}`:''}; <strong>Bulk</strong> ${esc(p.bulk||'—')}</p>${p.activation_actions||p.activation_frequency||p.activation_trigger||p.activation_requirements?`<hr class="fw-stat-divider"><p><strong>Activate</strong> ${act?`<span class="fw-action-glyphs">${act}</span>`:''}${p.activation_frequency?` ${esc(p.activation_frequency)}`:''}</p>${p.activation_trigger?`<p><strong>Trigger</strong> ${esc(p.activation_trigger)}</p>`:''}${p.activation_requirements?`<p><strong>Requirements</strong> ${esc(p.activation_requirements)}</p>`:''}`:''}<hr class="fw-stat-divider">${p.description?`<p class="fw-stat-desc">${lines(p.description)}</p>`:'<p class="fw-stat-desc">Describe the item’s rules here.</p>'}${abilityPreview(p.abilities)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`}
  function featPreview(d){const p=d.payload||{},act=actionGlyph(p.action_cost);return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top fw-feat-top"><h3>${esc(d.title||'Untitled feat')} ${act?`<span class="fw-action-glyphs">${act}</span>`:''}</h3><span class="fw-stat-level">FEAT ${esc(num(p.level,'1'))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml('feat',p)}<div class="fw-stat-body">${p.prerequisites?`<p><strong>Prerequisites</strong> ${esc(p.prerequisites)}</p>`:''}${p.frequency?`<p><strong>Frequency</strong> ${esc(p.frequency)}</p>`:''}${p.trigger?`<p><strong>Trigger</strong> ${esc(p.trigger)}</p>`:''}${p.requirements?`<p><strong>Requirements</strong> ${esc(p.requirements)}</p>`:''}${(p.prerequisites||p.frequency||p.trigger||p.requirements)?'<hr class="fw-stat-divider">':''}${p.description?`<p class="fw-stat-desc">${lines(p.description)}</p>`:'<p class="fw-stat-desc">Describe what the feat does.</p>'}${abilityPreview(p.abilities)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`}
  function homebrewPreview(d){const p=d.payload||{},act=actionGlyph(p.homebrew_actions);return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top fw-free-top"><h3>${esc(d.title||'Untitled homebrew')} ${act?`<span class="fw-action-glyphs">${act}</span>`:''}</h3><span class="fw-stat-level">${esc(String(p.homebrew_document||'HOMEBREW').toUpperCase())} ${esc(num(p.level,''))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml('homebrew',p)}<div class="fw-stat-body">${p.homebrew_frequency?`<p><strong>Frequency</strong> ${esc(p.homebrew_frequency)}</p>`:''}${p.homebrew_trigger?`<p><strong>Trigger</strong> ${esc(p.homebrew_trigger)}</p>`:''}${p.description?`<p class="fw-stat-desc">${lines(p.description)}</p>`:'<p class="fw-stat-desc">Freeform rules text goes here.</p>'}${abilityPreview(p.abilities)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`}
  function renderPreview(){
    syncRepeaters();const d=collectData(false);updateToolbar();
    if(!d.title && !d.summary && !(d.payload.description||'').trim() && !state.attacks.length && !state.abilities.length){preview.innerHTML='<div class="fw-statblock-empty"><span>✦</span><h3>Start with a name</h3><p>Your Pathfinder-style preview updates while you type.</p></div>';return}
    preview.innerHTML=creatureKind(d.kind)?creaturePreview(d):d.kind==='item'?itemPreview(d):d.kind==='feat'?featPreview(d):homebrewPreview(d);
  }

  async function refresh(){const data=await jsonFetch('/api/v61/foundry/workshop');state.actors=data.actors||[];state.entries=data.prepared_content||[];state.commands=data.commands||[];renderLibrary();renderLog()}
  async function saveCurrent({silent=false}={}){
    const data=collectData();if(!data.title)throw Error('Give this entry a name first.');
    const saved=await send('/api/v61/foundry/content','POST',data);state.currentId=saved.id;setField('id',saved.id);state.savedSnapshot=JSON.stringify(collectData());setDirty();$('[data-fw-duplicate]').disabled=false;if(!silent)toast('Homebrew saved.');await refresh();return saved
  }
  async function pushCurrent(target='world'){
    try{const saved=await saveCurrent({silent:true});const payload={target_type:target};if(target==='actor'){const actorId=$('[data-fw-actor-target]')?.value;if(!actorId)throw Error('Choose a Foundry actor first.');payload.actor_id=actorId}await send(`/api/v61/foundry/content/${saved.id}/push`,'POST',payload);toast(target==='actor'?'Queued for that actor.':'Queued for the Foundry world.');await refresh()}catch(e){toast(e.message||'Could not queue the Foundry push.',true)}
  }

  form.addEventListener('submit',async e=>{e.preventDefault();try{await saveCurrent()}catch(err){toast(err.message||'Could not save.',true)}});
  form.addEventListener('input',()=>{renderPreview();setDirty()});form.addEventListener('change',()=>{renderPreview();setDirty()});
  $$('[data-fw-kind]').forEach(b=>b.addEventListener('click',()=>setKind(b.dataset.fwKind)));
  $$('[data-fw-template]').forEach(b=>b.addEventListener('click',()=>{
    const key=b.dataset.fwTemplate;
    const presets={
      brute:{actor_role:'npc',size:'lg',str_mod:'4',dex_mod:'1',con_mod:'3',int_mod:'-1',wis_mod:'1',cha_mod:'0',speed:'25',summary:'A durable close-range threat that hits hard and controls space.'},
      skirmisher:{actor_role:'npc',size:'med',str_mod:'2',dex_mod:'4',con_mod:'2',int_mod:'0',wis_mod:'2',cha_mod:'0',speed:'35',summary:'A mobile threat that relies on positioning, speed, and agile attacks.'},
      caster:{actor_role:'npc',size:'med',str_mod:'0',dex_mod:'2',con_mod:'1',int_mod:'4',wis_mod:'3',cha_mod:'2',speed:'25',summary:'A spell-focused creature with a small number of memorable magical options.',spellcasting:'Prepared or spontaneous spells; add DC, attack modifier, and the few spells you expect to use.'},
      social:{actor_role:'npc',size:'med',str_mod:'0',dex_mod:'1',con_mod:'0',int_mod:'2',wis_mod:'2',cha_mod:'4',speed:'25',skills:'Diplomacy, Deception, Society',summary:'A conversation-first NPC built around influence, information, and social pressure.'},
      ally:{actor_role:'ally',size:'med',str_mod:'2',dex_mod:'2',con_mod:'2',int_mod:'0',wis_mod:'2',cha_mod:'1',speed:'25',summary:'A simple allied NPC designed to be useful without stealing the spotlight.'},
      consumable:{item_type:'consumable',quantity:'1',bulk:'L',usage:'held in 1 hand',summary:'A single-use item with one clear effect.'},
      weapon:{item_type:'weapon',quantity:'1',usage:'held in 1 or 2 hands',summary:'A distinctive weapon whose special rules are easy to read at the table.'},
      worn:{item_type:'equipment',quantity:'1',usage:'worn',summary:'A worn magic item with a passive benefit or a limited activation.'},
      'passive-feat':{feat_category:'general',action_cost:'',summary:'A passive feat that changes how the character approaches a recurring situation.'},
      'action-feat':{feat_category:'class',action_cost:'1',summary:'A one-action feat with a clear tactical purpose.'},
      'reaction-feat':{feat_category:'class',action_cost:'reaction',summary:'A reaction feat built around a precise trigger.'},
      'free-action':{homebrew_document:'action',homebrew_actions:'1',summary:'A custom rules element or action that does not fit another template.'},
      'free-item':{homebrew_document:'equipment',summary:'A custom item or rules object that does not fit another template.'},
    };
    const preset=presets[key]||{};Object.entries(preset).forEach(([k,v])=>setField(k,v));
    if(key==='brute' && !state.attacks.length)state.attacks=[{name:'Heavy Strike',type:'melee',bonus:'',damage:'',traits:''}];
    if(key==='skirmisher' && !state.attacks.length)state.attacks=[{name:'Agile Strike',type:'melee',bonus:'',damage:'',traits:'agile'}];
    if(key==='caster' && !state.abilities.length)state.abilities=[{name:'Signature Magic',actions:'2',traits:'magical',description:''}];
    renderRepeaters();renderPreview();setDirty();toast('Quick-start template applied. Fill in level-appropriate numbers.');
  }));
  $('[data-fw-add-attack]')?.addEventListener('click',()=>{syncRepeaters();state.attacks.push({name:'',type:'melee',bonus:'',damage:'',traits:''});renderRepeaters();renderPreview();setDirty();$('[data-fw-attacks] .fw-repeat-row:last-child input')?.focus()});
  $('[data-fw-add-ability]')?.addEventListener('click',()=>{syncRepeaters();state.abilities.push({name:'',actions:'',traits:'',description:''});renderRepeaters();renderPreview();setDirty();$('[data-fw-abilities] .fw-repeat-row:last-child input')?.focus()});
  root.addEventListener('click',e=>{const ra=e.target.closest('[data-remove-attack]');if(ra){syncRepeaters();state.attacks.splice(+ra.dataset.removeAttack,1);renderRepeaters();renderPreview();setDirty()}const rb=e.target.closest('[data-remove-ability]');if(rb){syncRepeaters();state.abilities.splice(+rb.dataset.removeAbility,1);renderRepeaters();renderPreview();setDirty()}});
  list.addEventListener('click',e=>{const b=e.target.closest('[data-fw-open]');if(!b)return;const entry=state.entries.find(x=>String(x.id)===String(b.dataset.fwOpen));if(entry){fillForm(entry);switchMobile('editor')}});
  $('[data-fw-new]')?.addEventListener('click',()=>{fillForm();switchMobile('editor')});
  $('[data-fw-duplicate]')?.addEventListener('click',()=>{const data=collectData();const copy={...data,id:null,title:`${data.title||'Untitled'} Copy`,payload:structuredClone(data.payload)};fillForm(copy);setField('id','');state.currentId=null;state.savedSnapshot='';setDirty();toast('Duplicated as a new unsaved entry.')});
  $('[data-fw-copy-json]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(JSON.stringify(collectData(),null,2));toast('Homebrew JSON copied.')}catch{toast('Could not access the clipboard.',true)}});
  $('[data-fw-preview-refresh]')?.addEventListener('click',renderPreview);
  $('[data-fw-push-world]')?.addEventListener('click',()=>pushCurrent('world'));
  $('[data-fw-push-actor]')?.addEventListener('click',()=>pushCurrent('actor'));
  $('[data-fw-search]')?.addEventListener('input',e=>{state.query=e.currentTarget.value;renderLibrary()});
  $$('[data-fw-filter]').forEach(b=>b.addEventListener('click',()=>{state.filter=b.dataset.fwFilter;$$('[data-fw-filter]').forEach(x=>x.classList.toggle('active',x===b));renderLibrary()}));
  $('[data-fw-import]')?.addEventListener('click',()=> $('[data-fw-import-file]')?.click());
  $('[data-fw-import-file]')?.addEventListener('change',async e=>{const file=e.currentTarget.files?.[0];if(!file)return;try{const data=JSON.parse(await file.text());if(!data||typeof data!=='object')throw Error('Invalid file.');data.id=null;fillForm(data);state.currentId=null;setField('id','');state.savedSnapshot='';setDirty();toast('Imported as an unsaved entry.')}catch(err){toast(err.message||'Could not import JSON.',true)}finally{e.currentTarget.value=''}});

  function switchMobile(view){root.querySelector('.fw-workspace')?.setAttribute('data-fw-mobile-view',view);$$('[data-fw-mobile]').forEach(b=>b.classList.toggle('active',b.dataset.fwMobile===view))}
  $$('[data-fw-mobile]').forEach(b=>b.addEventListener('click',()=>switchMobile(b.dataset.fwMobile)));

  // Restore only a genuinely unsaved local draft. Saved Seeker entries always win.
  let draft=null;try{draft=JSON.parse(localStorage.getItem('seeker-foundry-workshop-draft')||'null')}catch{}
  if(draft && !draft.id && (draft.title||draft.summary||draft.payload?.description)){fillForm(draft);state.currentId=null;state.savedSnapshot='';setDirty()}else{fillForm()}
  renderLibrary();renderLog();renderPreview();
})();
