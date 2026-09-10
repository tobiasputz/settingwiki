(()=>{
  const root=document.querySelector('[data-foundry-workshop]');
  if(!root) return;
  const initial=(()=>{try{return JSON.parse(document.getElementById('foundryWorkshopState')?.textContent||'{}')}catch{return {}}})();
  const state={actors:initial.actors||[],entries:initial.prepared_content||[],commands:initial.commands||[],filter:'all',query:'',attacks:[],abilities:[],spells:[],savedSnapshot:'',currentId:null,tokenImage:null,cropImage:null};
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
    updateItemSubtype();updateToolbar();renderPreview();setDirty();
  }
  function updateItemSubtype(){
    const weapon=fieldValue('kind')==='item'&&fieldValue('item_type')==='weapon';
    $('[data-fw-weapon-details]')?.classList.toggle('fw-hidden',!weapon);
  }
  function updateToolbar(){toolbarTitle.textContent=fieldValue('title').trim()||`Untitled ${kindName(fieldValue('kind')).toLowerCase()}`}

  function attackRow(row={},index=0){
    return `<div class="fw-repeat-row attack" data-attack-index="${index}">
      <label><span>Name</span><input data-rkey="name" value="${esc(row.name||'')}" placeholder="Claw"></label>
      <label><span>Type</span><select data-rkey="type"><option value="melee" ${row.type!=='ranged'?'selected':''}>Melee</option><option value="ranged" ${row.type==='ranged'?'selected':''}>Ranged</option></select></label>
      <label><span>Bonus</span><input data-rkey="bonus" type="number" step="1" value="${esc(row.bonus??'')}" placeholder="12"></label>
      <label><span>Damage</span><input data-rkey="damage" value="${esc(row.damage||'')}" placeholder="2d8+4"></label>
      <label><span>Damage type</span><select data-rkey="damage_type">${['bludgeoning','piercing','slashing','acid','cold','electricity','fire','force','mental','poison','sonic','spirit','vitality','void','bleed'].map(x=>`<option value="${x}" ${String(row.damage_type||'slashing')===x?'selected':''}>${x}</option>`).join('')}</select></label>
      <label><span>Range</span><input data-rkey="range" type="number" min="5" step="5" value="${esc(row.range??'')}" placeholder="30"></label>
      <button class="fw-remove-row" type="button" data-remove-attack="${index}" title="Remove strike">×</button>
      <label class="fw-repeat-traits"><span>Traits</span><input data-rkey="traits" value="${esc(row.traits||'')}" placeholder="agile, finesse, reach-10"></label>
      <label class="fw-repeat-traits"><span>Attack effects <em>optional</em></span><input data-rkey="effects" value="${esc(row.effects||'')}" placeholder="Grab, Knockdown…"></label>
    </div>`;
  }
  function abilityRow(row={},index=0){
    const actions=String(row.actions??'');
    const save=String(row.dc_type||'');
    const per=String(row.frequency_per||'');
    return `<div class="fw-repeat-row ability fw-ability-card" data-ability-index="${index}">
      <div class="fw-repeat-card-head">
        <label class="fw-ability-name"><span>Ability name</span><input data-rkey="name" value="${esc(row.name||'')}" placeholder="Cinder Step"></label>
        <button class="fw-remove-row" type="button" data-remove-ability="${index}" title="Remove ability">×</button>
      </div>
      <div class="fw-action-shortcuts" aria-label="Action cost">
        ${[['','Passive'],['free','◇ Free'],['reaction','↺ Reaction'],['1','◆ One'],['2','◆◆ Two'],['3','◆◆◆ Three']].map(([v,l])=>`<button type="button" class="${actions===v?'active':''}" data-ability-cost="${v}" data-ability-i="${index}">${l}</button>`).join('')}
        <input type="hidden" data-rkey="actions" value="${esc(actions)}">
      </div>
      <div class="fw-repeat-grid fw-ability-meta">
        <label><span>Section</span><select data-rkey="category"><option value="offensive" ${String(row.category||'offensive')==='offensive'?'selected':''}>Offensive / Actions</option><option value="defensive" ${row.category==='defensive'?'selected':''}>Defensive</option><option value="interaction" ${row.category==='interaction'?'selected':''}>Interaction</option></select></label>
        <label><span>Traits</span><input data-rkey="traits" value="${esc(row.traits||'')}" placeholder="fire, concentrate"></label>
        <label class="span-2"><span>Trigger <em>reaction / free action</em></span><input data-rkey="trigger" value="${esc(row.trigger||'')}" placeholder="A creature within 30 feet damages you"></label>
        <label class="span-2"><span>Requirements</span><input data-rkey="requirements" value="${esc(row.requirements||'')}" placeholder="The creature is standing in flame"></label>
      </div>
      <div class="fw-ability-toolbox">
        <div class="fw-ability-tool-head"><strong>Check / DC shortcut</strong><small>Creates a clickable PF2e check in Foundry.</small></div>
        <div class="fw-dc-shortcuts">
          ${[['fortitude','Fort'],['reflex','Ref'],['will','Will'],['acrobatics','Acrobatics'],['athletics','Athletics'],['perception','Perception']].map(([v,l])=>`<button type="button" class="${save===v?'active':''}" data-ability-dc-type="${v}" data-ability-i="${index}">${l}</button>`).join('')}
          <button type="button" data-ability-clear-dc data-ability-i="${index}">No check</button>
          <input type="hidden" data-rkey="dc_type" value="${esc(save)}">
        </div>
        <div class="fw-repeat-grid compact">
          <label><span>DC</span><input data-rkey="dc" type="number" min="0" step="1" value="${esc(row.dc??'')}" placeholder="22"></label>
          <label><span>Visibility</span><select data-rkey="dc_show"><option value="owner" ${!row.dc_show||row.dc_show==='owner'?'selected':''}>Normal</option><option value="all" ${row.dc_show==='all'?'selected':''}>Show DC</option><option value="gm" ${row.dc_show==='gm'?'selected':''}>GM only</option><option value="none" ${row.dc_show==='none'?'selected':''}>Hide DC</option></select></label>
          <label class="fw-inline-check"><input data-rkey="dc_basic" type="checkbox" ${row.dc_basic?'checked':''}> <span>Basic save</span></label>
          <button class="quiet-btn fw-use-spell-dc" type="button" data-ability-use-spell-dc data-ability-i="${index}">Use creature spell DC</button>
        </div>
      </div>
      <div class="fw-ability-toolbox">
        <div class="fw-ability-tool-head"><strong>Damage shortcut</strong><small>Optional clickable damage roll.</small></div>
        <div class="fw-repeat-grid compact">
          <label><span>Damage</span><input data-rkey="damage" value="${esc(row.damage||'')}" placeholder="4d6+8"></label>
          <label><span>Type</span><select data-rkey="damage_type">${['bludgeoning','piercing','slashing','acid','cold','electricity','fire','force','mental','poison','sonic','spirit','vitality','void','bleed'].map(x=>`<option value="${x}" ${String(row.damage_type||'fire')===x?'selected':''}>${x}</option>`).join('')}</select></label>
        </div>
      </div>
      <div class="fw-ability-toolbox">
        <div class="fw-ability-tool-head"><strong>Frequency</strong><small>Leave blank for unlimited use.</small></div>
        <div class="fw-repeat-grid compact">
          <label><span>Uses</span><input data-rkey="frequency_max" type="number" min="1" step="1" value="${esc(row.frequency_max??'')}" placeholder="1"></label>
          <label><span>Per</span><select data-rkey="frequency_per"><option value="" ${!per?'selected':''}>Unlimited</option><option value="turn" ${per==='turn'?'selected':''}>Turn</option><option value="round" ${per==='round'?'selected':''}>Round</option><option value="PT1M" ${per==='PT1M'?'selected':''}>1 minute</option><option value="PT10M" ${per==='PT10M'?'selected':''}>10 minutes</option><option value="PT1H" ${per==='PT1H'?'selected':''}>Hour</option><option value="PT24H" ${per==='PT24H'?'selected':''}>24 hours</option><option value="day" ${per==='day'?'selected':''}>Day</option><option value="P1W" ${per==='P1W'?'selected':''}>Week</option></select></label>
        </div>
      </div>
      <div class="fw-ability-presets"><small>QUICK START</small><button type="button" data-ability-template="breath" data-ability-i="${index}">Breath / save</button><button type="button" data-ability-template="reaction" data-ability-i="${index}">Reaction</button><button type="button" data-ability-template="aura" data-ability-i="${index}">Passive aura</button><button type="button" data-ability-template="recharge" data-ability-i="${index}">Once / round</button></div>
      <textarea data-rkey="description" placeholder="Ability rules text…">${esc(row.description||'')}</textarea>
    </div>`;
  }
  function spellRow(row={},index=0){
    return `<div class="fw-repeat-row spell fw-spell-card" data-spell-index="${index}">
      <div class="fw-repeat-card-head">
        <label class="fw-spell-name"><span>Spell name</span><input data-rkey="name" value="${esc(row.name||'')}" placeholder="Fireball"></label>
        <button class="fw-remove-row" type="button" data-remove-spell="${index}" title="Remove spell">×</button>
      </div>
      <div class="fw-repeat-grid fw-spell-core">
        <label><span>Rank</span><input data-rkey="rank" type="number" min="0" max="10" step="1" value="${esc(row.rank??'')}" placeholder="3"></label>
        <label><span>Cast</span><select data-rkey="actions"><option value="1" ${row.actions==='1'?'selected':''}>◆ 1</option><option value="2" ${!row.actions||row.actions==='2'?'selected':''}>◆◆ 2</option><option value="3" ${row.actions==='3'?'selected':''}>◆◆◆ 3</option><option value="reaction" ${row.actions==='reaction'?'selected':''}>↺ Reaction</option><option value="free" ${row.actions==='free'?'selected':''}>◇ Free</option><option value="1 minute" ${row.actions==='1 minute'?'selected':''}>1 minute</option><option value="10 minutes" ${row.actions==='10 minutes'?'selected':''}>10 minutes</option></select></label>
        <label><span>Innate uses</span><input data-rkey="uses" type="number" min="1" max="99" step="1" value="${esc(row.uses??'1')}" placeholder="1"></label>
        <label><span>Range</span><input data-rkey="range" value="${esc(row.range||'')}" placeholder="500 feet"></label>
        <label class="span-2"><span>Target / area</span><input data-rkey="target" value="${esc(row.target||'')}" placeholder="20-foot burst"></label>
        <label><span>Defense</span><select data-rkey="save"><option value="" ${!row.save?'selected':''}>None / spell attack</option><option value="fortitude" ${row.save==='fortitude'?'selected':''}>Fortitude</option><option value="reflex" ${row.save==='reflex'?'selected':''}>Reflex</option><option value="will" ${row.save==='will'?'selected':''}>Will</option><option value="ac" ${row.save==='ac'?'selected':''}>AC</option></select></label>
        <label class="fw-inline-check"><input data-rkey="basic" type="checkbox" ${row.basic?'checked':''}> <span>Basic save</span></label>
        <label><span>Damage</span><input data-rkey="damage" value="${esc(row.damage||'')}" placeholder="6d6"></label>
        <label><span>Damage type</span><select data-rkey="damage_type">${['fire','cold','electricity','acid','bludgeoning','piercing','slashing','force','mental','poison','sonic','spirit','vitality','void'].map(x=>`<option value="${x}" ${String(row.damage_type||'fire')===x?'selected':''}>${x}</option>`).join('')}</select></label>
        <label><span>Duration</span><input data-rkey="duration" value="${esc(row.duration||'')}" placeholder="1 minute"></label>
        <label><span>Traits</span><input data-rkey="traits" value="${esc(row.traits||'')}" placeholder="fire, manipulate, concentrate"></label>
        <label class="span-2"><span>Compendium UUID <em>optional, exact</em></span><input data-rkey="source_uuid" value="${esc(row.source_uuid||'')}" placeholder="Compendium.pf2e.spells-srd.Item.…"></label>
      </div>
      <div class="fw-spell-match-note"><strong>Official spell lookup:</strong> paste a compendium UUID for an exact import, or enter a spell name and Seeker searches installed PF2e spell packs. If neither resolves, it creates your structured homebrew version.</div>
      <textarea data-rkey="description" placeholder="Homebrew spell effect / rules text… (ignored when an official compendium spell is matched)">${esc(row.description||'')}</textarea>
    </div>`;
  }
  function renderRepeaters(){
    const a=$('[data-fw-attacks]'),b=$('[data-fw-abilities]'),s=$('[data-fw-spells]');
    if(a)a.innerHTML=state.attacks.length?state.attacks.map(attackRow).join(''):'<div class="fw-repeater-empty">No strikes yet. Add only the attacks you expect to use.</div>';
    if(b)b.innerHTML=state.abilities.length?state.abilities.map(abilityRow).join(''):'<div class="fw-repeater-empty">No special abilities yet. Add reactions, passive abilities, activated powers, or signature tricks here.</div>';
    if(s)s.innerHTML=state.spells.length?state.spells.map(spellRow).join(''):'<div class="fw-repeater-empty">No structured spells yet. Add spells here if you want them to appear as real Foundry spells.</div>';
  }
  function syncRepeaters(){
    $$('[data-attack-index]').forEach(row=>{const i=+row.dataset.attackIndex;state.attacks[i] ||= {};$$('[data-rkey]',row).forEach(el=>state.attacks[i][el.dataset.rkey]=el.type==='checkbox'?el.checked:el.value)});
    $$('[data-ability-index]').forEach(row=>{const i=+row.dataset.abilityIndex;state.abilities[i] ||= {};$$('[data-rkey]',row).forEach(el=>state.abilities[i][el.dataset.rkey]=el.type==='checkbox'?el.checked:el.value)});
    $$('[data-spell-index]').forEach(row=>{const i=+row.dataset.spellIndex;state.spells[i] ||= {};$$('[data-rkey]',row).forEach(el=>state.spells[i][el.dataset.rkey]=el.type==='checkbox'?el.checked:el.value)});
  }

  const payloadFields=['img','token_img','level','rarity','size','actor_role','traits','item_type','feat_category','homebrew_document','price','bulk','usage','hands','quantity','item_category','action_cost','frequency','prerequisites','trigger','requirements','activation_actions','activation_frequency','activation_trigger','activation_requirements','homebrew_actions','homebrew_frequency','homebrew_trigger','perception','speed','senses','languages','skills','ac','fortitude','reflex','will','hp','immunities','weaknesses','resistances','str_mod','dex_mod','con_mod','int_mod','wis_mod','cha_mod','description','spellcasting','spell_tradition','spell_mode','spell_dc','spell_attack','gm_notes','codex_visibility','codex_category','codex_blurb','weapon_category','weapon_group','weapon_damage_dice','weapon_damage_die','weapon_damage_type','weapon_damage_modifier','weapon_bonus','weapon_usage','weapon_range','weapon_reload','weapon_potency','weapon_striking','weapon_base'];
  function collectData(sync=true){
    if(sync)syncRepeaters();
    const kind=fieldValue('kind')||'monster';
    const payload={};payloadFields.forEach(k=>payload[k]=fieldValue(k));payload.codex_publish=!!field('codex_publish')?.checked;payload.attacks=state.attacks;payload.abilities=state.abilities;payload.spells=state.spells;
    return {id:fieldValue('id')||undefined,kind,target_type:'world',title:fieldValue('title').trim(),subtitle:fieldValue('subtitle').trim(),summary:fieldValue('summary'),tags:fieldValue('traits'),payload};
  }
  function fillForm(entry=null){
    form.reset();state.currentId=entry?.id||null;state.attacks=[];state.abilities=[];state.spells=[];
    setField('id',entry?.id||'');setField('title',entry?.title||'');setField('subtitle',entry?.subtitle||'');setField('summary',entry?.summary||'');
    const p=entry?.payload||{};payloadFields.forEach(k=>setField(k,p[k]??''));
    if(!entry){setField('level','1');setField('rarity','common');setField('size','med');setField('quantity','1');setField('weapon_category','simple');setField('weapon_damage_dice','1');setField('weapon_damage_die','d6');setField('weapon_damage_type','slashing');setField('weapon_damage_modifier','0');setField('weapon_bonus','0');setField('weapon_usage','held-in-one-hand');setField('weapon_potency','0');setField('weapon_striking','0');['str_mod','dex_mod','con_mod','int_mod','wis_mod','cha_mod'].forEach(k=>setField(k,'0'))}
    if(field('codex_publish'))field('codex_publish').checked=!!p.codex_publish;
    state.attacks=Array.isArray(p.attacks)?structuredClone(p.attacks):[];state.abilities=Array.isArray(p.abilities)?structuredClone(p.abilities):[];state.spells=Array.isArray(p.spells)?structuredClone(p.spells):[];
    setKind(entry?.kind||'monster');renderRepeaters();updateItemSubtype();updateArtStatus();updateToolbar();renderPreview();
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
    log.innerHTML=rows.length?rows.slice(0,25).map(r=>`<article class="command-log-item" data-command-row="${esc(r.id)}"><span class="status ${esc(r.status||'queued')}">${esc(r.delivery_label||r.status||'queued')}</span><strong>${esc(String(r.command_type||'action').replaceAll('_',' '))}</strong><small>${esc(r.requested_by||'GM')} · ${esc(r.actor_id||'world')} · attempt ${esc(r.attempt_count||0)}</small>${r.last_error?`<div class="command-error">${esc(r.last_error)}</div>`:(r.result?.message?`<div>${esc(r.result.message)}</div>`:'')}${r.can_retry?`<button class="quiet-btn command-retry" type="button" data-retry-command="${esc(r.id)}">Retry delivery</button>`:''}</article>`).join(''):'<p class="muted">No bridge actions yet.</p>';
  }

  function traitHtml(kind,p){const rarity=String(p.rarity||'common');const raw=[rarity!=='common'?rarity:'',creatureKind(kind)?p.size:'',...slugList(p.traits)].filter(Boolean);return raw.length?`<div class="fw-preview-traits ${kind==='item'?'fw-item-traits':kind==='feat'?'fw-feat-traits':kind==='homebrew'?'fw-free-traits':''}">${raw.map((t,i)=>`<span class="${i===0&&rarity!=='common'?`rarity-${esc(rarity)}`:''}">${esc(t)}</span>`).join('')}</div>`:''}
  function abilityPreview(rows){return (rows||[]).filter(a=>a.name||a.description).map(a=>{const check=a.dc_type&&a.dc?`<p><strong>${esc(String(a.dc_type).replace(/^./,c=>c.toUpperCase()))} DC ${esc(a.dc)}</strong>${a.dc_basic?' basic':''}</p>`:'';const dmg=a.damage?`<p><strong>Damage</strong> ${esc(a.damage)} ${esc(a.damage_type||'')}</p>`:'';const freq=a.frequency_per?`<small>${esc(a.frequency_max||1)} / ${esc(a.frequency_per)}</small>`:'';return `<div class="fw-stat-action"><h4>${esc(a.name||'Ability')} ${a.actions?`<span class="fw-action-glyphs">${actionGlyph(a.actions)}</span>`:''}</h4>${a.traits?`<small>${esc(a.traits)}</small>`:''}${freq}${a.trigger?`<p><strong>Trigger</strong> ${esc(a.trigger)}</p>`:''}${a.requirements?`<p><strong>Requirements</strong> ${esc(a.requirements)}</p>`:''}${check}${dmg}${a.description?`<p>${lines(a.description)}</p>`:''}</div>`}).join('')}
  function spellPreview(p){
    const rows=(p.spells||[]).filter(s=>s.name||s.description);
    if(!rows.length)return p.spellcasting?`<div class="fw-stat-action"><h4>Spellcasting</h4><p>${lines(p.spellcasting)}</p></div>`:'';
    const tradition=String(p.spell_tradition||'arcane');
    const head=`${tradition.charAt(0).toUpperCase()+tradition.slice(1)} ${String(p.spell_mode||'innate').replace(/^./,c=>c.toUpperCase())} Spells${String(p.spell_dc||'').trim()?` DC ${esc(p.spell_dc)}`:''}${String(p.spell_dc||'').trim()?`, attack ${signed(String(p.spell_attack||'').trim()||String(Math.max(0,Number(p.spell_dc||0)-8)))}`:''}`;
    const grouped=new Map();rows.forEach(s=>{const r=Number(s.rank||0);if(!grouped.has(r))grouped.set(r,[]);grouped.get(r).push(s)});
    return `<div class="fw-stat-action"><h4>${esc(head)}</h4>${[...grouped.entries()].sort((a,b)=>b[0]-a[0]).map(([rank,spells])=>`<p><strong>${rank===0?'Cantrips':`Rank ${rank}`}</strong> ${spells.map(s=>`${esc(s.name)}${s.damage?` (${esc(s.damage)} ${esc(s.damage_type||'')})`:''}`).join(', ')}</p>`).join('')}${p.spellcasting?`<p>${lines(p.spellcasting)}</p>`:''}</div>`;
  }
  function creaturePreview(d){const p=d.payload||{},kind=d.kind;const abs=[['STR',p.str_mod],['DEX',p.dex_mod],['CON',p.con_mod],['INT',p.int_mod],['WIS',p.wis_mod],['CHA',p.cha_mod]];
    const defenses=[`<strong>AC</strong> ${num(p.ac)}`,`<strong>Fort</strong> ${signed(p.fortitude)}`,`<strong>Ref</strong> ${signed(p.reflex)}`,`<strong>Will</strong> ${signed(p.will)}`].join('; ');
    const extras=[p.immunities?`<strong>Immunities</strong> ${esc(p.immunities)}`:'',p.weaknesses?`<strong>Weaknesses</strong> ${esc(p.weaknesses)}`:'',p.resistances?`<strong>Resistances</strong> ${esc(p.resistances)}`:''].filter(Boolean).join('; ');
    const attacks=(p.attacks||[]).filter(x=>x.name||x.damage).map(a=>`<p class="fw-stat-strike"><strong>${a.type==='ranged'?'Ranged':'Melee'}</strong> ${esc(a.name||'Strike')} ${signed(a.bonus)}${a.traits?` (${esc(a.traits)})`:''}, <strong>Damage</strong> ${esc(a.damage||'—')}</p>`).join('');
    return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top"><h3>${esc(d.title||'Untitled creature')}</h3><span class="fw-stat-level">${kind==='npc'?'NPC':'CREATURE'} ${esc(num(p.level,'1'))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml(kind,p)}<div class="fw-stat-body">
      <p><strong>Perception</strong> ${signed(p.perception)}${p.senses?`; ${esc(p.senses)}`:''}</p>${p.languages?`<p><strong>Languages</strong> ${esc(p.languages)}</p>`:''}${p.skills?`<p><strong>Skills</strong> ${esc(p.skills)}</p>`:''}
      <div class="fw-stat-abilities">${abs.map(([a,v])=>`<span><strong>${a}</strong> ${signed(v)}</span>`).join('')}</div><hr class="fw-stat-divider">
      <p>${defenses}</p><p><strong>HP</strong> ${num(p.hp)}${extras?`; ${extras}`:''}</p><hr class="fw-stat-divider">
      <p><strong>Speed</strong> ${num(p.speed,'25')} feet</p>${attacks}${p.description?`<div class="fw-stat-action"><p class="fw-stat-desc">${lines(p.description)}</p></div>`:''}${abilityPreview(p.abilities)}${spellPreview(p)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`;
  }
  function itemPreview(d){
    const p=d.payload||{},act=actionGlyph(p.activation_actions),weapon=p.item_type==='weapon';
    const dice=weapon?`${num(p.weapon_damage_dice,'1')}${esc(p.weapon_damage_die||'d6')}${Number(p.weapon_damage_modifier||0)?`${Number(p.weapon_damage_modifier)>0?'+':''}${esc(p.weapon_damage_modifier)}`:''} ${esc(p.weapon_damage_type||'slashing')}`:'';
    const weaponMeta=weapon?`<hr class="fw-stat-divider"><p><strong>Weapon</strong> ${esc(p.weapon_category||'simple')}${p.weapon_group?` · ${esc(p.weapon_group)} group`:''}${p.weapon_range?` · range ${esc(p.weapon_range)} ft`:''}${p.weapon_reload?` · reload ${esc(p.weapon_reload)}`:''}</p><p><strong>Damage</strong> ${dice}${Number(p.weapon_bonus||0)?`; <strong>Item bonus</strong> ${signed(p.weapon_bonus)}`:''}${Number(p.weapon_potency||0)?`; <strong>Potency</strong> +${esc(p.weapon_potency)}`:''}${Number(p.weapon_striking||0)?`; <strong>Striking</strong> ${esc(p.weapon_striking)}`:''}</p>`:'';
    return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top fw-item-top"><h3>${esc(d.title||'Untitled item')}</h3><span class="fw-stat-level">ITEM ${esc(num(p.level,'0'))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml('item',p)}<div class="fw-stat-body">${p.price?`<p><strong>Price</strong> ${esc(p.price)}</p>`:''}<p><strong>Usage</strong> ${esc(p.usage||p.weapon_usage||'—')}${p.hands?`; <strong>Hands</strong> ${esc(p.hands)}`:''}; <strong>Bulk</strong> ${esc(p.bulk||'—')}</p>${weaponMeta}${p.activation_actions||p.activation_frequency||p.activation_trigger||p.activation_requirements?`<hr class="fw-stat-divider"><p><strong>Activate</strong> ${act?`<span class="fw-action-glyphs">${act}</span>`:''}${p.activation_frequency?` ${esc(p.activation_frequency)}`:''}</p>${p.activation_trigger?`<p><strong>Trigger</strong> ${esc(p.activation_trigger)}</p>`:''}${p.activation_requirements?`<p><strong>Requirements</strong> ${esc(p.activation_requirements)}</p>`:''}`:''}<hr class="fw-stat-divider">${p.description?`<p class="fw-stat-desc">${lines(p.description)}</p>`:'<p class="fw-stat-desc">Describe the item’s rules here.</p>'}${abilityPreview(p.abilities)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`
  }
  function featPreview(d){const p=d.payload||{},act=actionGlyph(p.action_cost);return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top fw-feat-top"><h3>${esc(d.title||'Untitled feat')} ${act?`<span class="fw-action-glyphs">${act}</span>`:''}</h3><span class="fw-stat-level">FEAT ${esc(num(p.level,'1'))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml('feat',p)}<div class="fw-stat-body">${p.prerequisites?`<p><strong>Prerequisites</strong> ${esc(p.prerequisites)}</p>`:''}${p.frequency?`<p><strong>Frequency</strong> ${esc(p.frequency)}</p>`:''}${p.trigger?`<p><strong>Trigger</strong> ${esc(p.trigger)}</p>`:''}${p.requirements?`<p><strong>Requirements</strong> ${esc(p.requirements)}</p>`:''}${(p.prerequisites||p.frequency||p.trigger||p.requirements)?'<hr class="fw-stat-divider">':''}${p.description?`<p class="fw-stat-desc">${lines(p.description)}</p>`:'<p class="fw-stat-desc">Describe what the feat does.</p>'}${abilityPreview(p.abilities)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`}
  function homebrewPreview(d){const p=d.payload||{},act=actionGlyph(p.homebrew_actions);return `${p.img?`<img class="fw-preview-image" src="${esc(p.img)}" alt="">`:''}<header class="fw-stat-top fw-free-top"><h3>${esc(d.title||'Untitled homebrew')} ${act?`<span class="fw-action-glyphs">${act}</span>`:''}</h3><span class="fw-stat-level">${esc(String(p.homebrew_document||'HOMEBREW').toUpperCase())} ${esc(num(p.level,''))}</span></header>${d.subtitle?`<div class="fw-stat-subtitle">${esc(d.subtitle)}</div>`:''}${traitHtml('homebrew',p)}<div class="fw-stat-body">${p.homebrew_frequency?`<p><strong>Frequency</strong> ${esc(p.homebrew_frequency)}</p>`:''}${p.homebrew_trigger?`<p><strong>Trigger</strong> ${esc(p.homebrew_trigger)}</p>`:''}${p.description?`<p class="fw-stat-desc">${lines(p.description)}</p>`:'<p class="fw-stat-desc">Freeform rules text goes here.</p>'}${abilityPreview(p.abilities)}${d.summary?`<div class="fw-preview-note">${lines(d.summary)}</div>`:''}</div>`}
  function renderPreview(){
    syncRepeaters();const d=collectData(false);updateToolbar();
    if(!d.title && !d.summary && !(d.payload.description||'').trim() && !state.attacks.length && !state.abilities.length){preview.innerHTML='<div class="fw-statblock-empty"><span>✦</span><h3>Start with a name</h3><p>Your Pathfinder-style preview updates while you type.</p></div>';return}
    preview.innerHTML=creatureKind(d.kind)?creaturePreview(d):d.kind==='item'?itemPreview(d):d.kind==='feat'?featPreview(d):homebrewPreview(d);
  }

  async function refresh(){const data=await jsonFetch('/api/v61/foundry/workshop');state.actors=data.actors||[];state.entries=data.prepared_content||[];state.commands=data.commands||[];renderLibrary();renderLog()}
  log?.addEventListener('click',async e=>{const b=e.target.closest('[data-retry-command]');if(!b)return;b.disabled=true;try{await send(`/api/v6/foundry/commands/${b.dataset.retryCommand}/retry`,'POST',{});toast('Foundry delivery queued again.');await refresh()}catch(err){toast(err.message||'Could not retry delivery.',true)}finally{b.disabled=false}});
  async function saveCurrent({silent=false}={}){
    const data=collectData();if(!data.title)throw Error('Give this entry a name first.');
    const saved=await send('/api/v61/foundry/content','POST',data);state.currentId=saved.id;setField('id',saved.id);state.savedSnapshot=JSON.stringify(collectData());setDirty();$('[data-fw-duplicate]').disabled=false;if(!silent)toast('Homebrew saved.');await refresh();return saved
  }
  async function pushCurrent(target='world'){
    try{
      const saved=await saveCurrent({silent:true});const payload={target_type:target};
      if(target==='actor'){const actorId=$('[data-fw-actor-target]')?.value;if(!actorId)throw Error('Choose a Foundry actor first.');payload.actor_id=actorId}
      const queued=await send(`/api/v61/foundry/content/${saved.id}/push`,'POST',payload);
      const commandId=queued?.command?.id;
      toast(target==='actor'?'Sent to Foundry — waiting for the actor refresh.':'Sent to Foundry — waiting for the world refresh.');
      await refresh();
      // Force a visible Seeker refresh as soon as Foundry acknowledges the command.
      // The bridge itself also pushes a fresh actor/world snapshot immediately after
      // execution, so the next render reflects the actual Foundry document.
      if(commandId){
        const started=Date.now();
        const watch=async()=>{
          try{
            await refresh();
            const row=state.commands.find(c=>String(c.id)===String(commandId));
            if(row?.status==='done'){renderPreview();toast('Foundry applied it — Seeker refreshed.');return}
            if(row?.status==='failed'){toast(row?.result?.message||'Foundry rejected part of the import.',true);return}
          }catch{}
          if(Date.now()-started<15000)setTimeout(watch,1000);
          else{await refresh().catch(()=>{});renderPreview()}
        };
        setTimeout(watch,700);
      }else{setTimeout(()=>refresh().catch(()=>{}),3200)}
    }catch(e){toast(e.message||'Could not queue the Foundry push.',true)}
  }

  form.addEventListener('submit',async e=>{e.preventDefault();try{await saveCurrent()}catch(err){toast(err.message||'Could not save.',true)}});
  form.addEventListener('input',()=>{renderPreview();setDirty()});form.addEventListener('change',e=>{if(e.target?.name==='item_type')updateItemSubtype();renderPreview();setDirty()});
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
      weapon:{item_type:'weapon',quantity:'1',usage:'held in 1 hand',weapon_category:'martial',weapon_group:'sword',weapon_damage_dice:'1',weapon_damage_die:'d8',weapon_damage_type:'slashing',weapon_damage_modifier:'0',weapon_bonus:'0',weapon_usage:'held-in-one-hand',weapon_potency:'0',weapon_striking:'0',summary:'A distinctive weapon with complete PF2e strike data and readable special rules.'},
      worn:{item_type:'equipment',quantity:'1',usage:'worn',summary:'A worn magic item with a passive benefit or a limited activation.'},
      'passive-feat':{feat_category:'general',action_cost:'',summary:'A passive feat that changes how the character approaches a recurring situation.'},
      'action-feat':{feat_category:'class',action_cost:'1',summary:'A one-action feat with a clear tactical purpose.'},
      'reaction-feat':{feat_category:'class',action_cost:'reaction',summary:'A reaction feat built around a precise trigger.'},
      'free-action':{homebrew_document:'action',homebrew_actions:'1',summary:'A custom rules element or action that does not fit another template.'},
      'free-item':{homebrew_document:'equipment',summary:'A custom item or rules object that does not fit another template.'},
    };
    const preset=presets[key]||{};Object.entries(preset).forEach(([k,v])=>setField(k,v));
    if(key==='brute' && !state.attacks.length)state.attacks=[{name:'Heavy Strike',type:'melee',bonus:'',damage:'',damage_type:'bludgeoning',range:'',traits:'',effects:''}];
    if(key==='skirmisher' && !state.attacks.length)state.attacks=[{name:'Agile Strike',type:'melee',bonus:'',damage:'',damage_type:'slashing',range:'',traits:'agile',effects:''}];
    if(key==='caster' && !state.abilities.length)state.abilities=[{name:'Signature Magic',actions:'2',traits:'magical',description:''}];
    updateItemSubtype();renderRepeaters();renderPreview();setDirty();toast('Quick-start template applied. Fill in level-appropriate numbers.');
  }));
  $('[data-fw-add-attack]')?.addEventListener('click',()=>{syncRepeaters();state.attacks.push({name:'',type:'melee',bonus:'',damage:'',damage_type:'slashing',range:'',traits:'',effects:''});renderRepeaters();renderPreview();setDirty();$('[data-fw-attacks] .fw-repeat-row:last-child input')?.focus()});
  $('[data-fw-add-ability]')?.addEventListener('click',()=>{syncRepeaters();state.abilities.push({name:'',actions:'',category:'offensive',traits:'',trigger:'',requirements:'',dc_type:'',dc:'',dc_basic:false,dc_show:'owner',damage:'',damage_type:'fire',frequency_max:'',frequency_per:'',description:''});renderRepeaters();renderPreview();setDirty();$('[data-fw-abilities] .fw-repeat-row:last-child input')?.focus()});
  $('[data-fw-add-spell]')?.addEventListener('click',()=>{syncRepeaters();state.spells.push({name:'',rank:'1',actions:'2',uses:'1',range:'',target:'',save:'',basic:false,damage:'',damage_type:'fire',traits:'',duration:'',source_uuid:'',description:''});renderRepeaters();renderPreview();setDirty();$('[data-fw-spells] .fw-repeat-row:last-child input')?.focus()});
  root.addEventListener('click',e=>{
    const ra=e.target.closest('[data-remove-attack]');if(ra){syncRepeaters();state.attacks.splice(+ra.dataset.removeAttack,1);renderRepeaters();renderPreview();setDirty();return}
    const rb=e.target.closest('[data-remove-ability]');if(rb){syncRepeaters();state.abilities.splice(+rb.dataset.removeAbility,1);renderRepeaters();renderPreview();setDirty();return}
    const rs=e.target.closest('[data-remove-spell]');if(rs){syncRepeaters();state.spells.splice(+rs.dataset.removeSpell,1);renderRepeaters();renderPreview();setDirty();return}
    const cost=e.target.closest('[data-ability-cost]');if(cost){syncRepeaters();const i=+cost.dataset.abilityI;state.abilities[i].actions=cost.dataset.abilityCost||'';renderRepeaters();renderPreview();setDirty();return}
    const dtype=e.target.closest('[data-ability-dc-type]');if(dtype){syncRepeaters();const i=+dtype.dataset.abilityI;state.abilities[i].dc_type=dtype.dataset.abilityDcType||'';renderRepeaters();renderPreview();setDirty();return}
    const clear=e.target.closest('[data-ability-clear-dc]');if(clear){syncRepeaters();const i=+clear.dataset.abilityI;state.abilities[i].dc_type='';state.abilities[i].dc='';renderRepeaters();renderPreview();setDirty();return}
    const use=e.target.closest('[data-ability-use-spell-dc]');if(use){syncRepeaters();const i=+use.dataset.abilityI;const dc=fieldValue('spell_dc').trim();if(!dc)return toast('Enter the creature spell DC first.',true);state.abilities[i].dc=dc;renderRepeaters();renderPreview();setDirty();return}
    const preset=e.target.closest('[data-ability-template]');if(preset){syncRepeaters();const i=+preset.dataset.abilityI,a=state.abilities[i];const key=preset.dataset.abilityTemplate;if(key==='breath'){Object.assign(a,{actions:'2',dc_type:a.dc_type||'reflex',dc_basic:true,damage:a.damage||'4d6',damage_type:a.damage_type||'fire',category:'offensive'})}else if(key==='reaction'){Object.assign(a,{actions:'reaction',category:'defensive'})}else if(key==='aura'){Object.assign(a,{actions:'',category:'defensive',traits:a.traits||'aura'})}else if(key==='recharge'){Object.assign(a,{frequency_max:'1',frequency_per:'round'})}renderRepeaters();renderPreview();setDirty();return}
    const common=e.target.closest('[data-fw-common-spell]');if(common){syncRepeaters();state.spells.push({name:common.dataset.fwCommonSpell,rank:common.dataset.fwSpellRank||'1',actions:common.dataset.fwSpellActions||'2',uses:'1',range:'',target:'',save:'',basic:false,damage:'',damage_type:'fire',traits:'',duration:'',source_uuid:'',description:''});renderRepeaters();renderPreview();setDirty();return}
  });
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

  async function uploadFoundryAsset(file,kind='art'){
    const fd=new FormData();fd.append('image',file);fd.append('kind',kind);
    const r=await fetch('/api/v61/foundry/assets',{method:'POST',body:fd});
    const body=await r.json().catch(()=>({}));if(!r.ok)throw Error(body.detail||'Image upload failed.');return body;
  }
  const artStatus=$('[data-fw-art-status]');
  function updateArtStatus(out=null){
    const raw=fieldValue('img').trim();
    if(!artStatus)return;
    if(out?.bytes){artStatus.textContent=`Stored efficiently in Seeker · ${out.width}×${out.height} WebP · ${Math.max(1,Math.round(out.bytes/1024))} KB.`;return}
    if(raw.startsWith('/uploads/foundry/')){artStatus.textContent='Stored locally in Seeker as optimized WebP. Token Forge and crop tools can use it safely.';return}
    if(/^https?:\/\//i.test(raw)){artStatus.textContent='External artwork link. Import it before cropping/token creation; Seeker will optimize and deduplicate the local copy.';return}
    artStatus.textContent='Uploaded/imported art is automatically resized, compressed to WebP, and deduplicated in Seeker.';
  }
  async function importLinkedArt(){
    const raw=fieldValue('img').trim();
    if(!raw)throw Error('Enter an artwork URL first.');
    let parsed;try{parsed=new URL(raw,location.href)}catch{throw Error('That artwork URL is not valid.')}
    if(parsed.origin===location.origin){updateArtStatus();return raw}
    if(!/^https?:$/i.test(parsed.protocol))throw Error('Use a public http(s) artwork URL.');
    const out=await send('/api/v61/foundry/assets/import','POST',{url:raw,kind:'art'});
    setField('img',out.url);updateArtStatus(out);renderPreview();setDirty();
    toast('Linked artwork imported and optimized.');
    return out.url;
  }
  async function ensureEditableArt(){
    const raw=fieldValue('img').trim();
    if(!raw)throw Error('Add portrait artwork first.');
    try{const u=new URL(raw,location.href);if(u.origin!==location.origin&&/^https?:$/.test(u.protocol))return await importLinkedArt()}catch{}
    return raw;
  }
  $('[data-fw-art-import]')?.addEventListener('click',async()=>{try{await importLinkedArt()}catch(err){toast(err.message,true)}});
  field('img')?.addEventListener('change',updateArtStatus);
  $('[data-fw-art-upload]')?.addEventListener('change',async e=>{
    const file=e.currentTarget.files?.[0];if(!file)return;
    try{const out=await uploadFoundryAsset(file,'art');setField('img',out.url);updateArtStatus(out);renderPreview();setDirty();toast('Artwork optimized and stored in Seeker. You can crop it if desired.')}catch(err){toast(err.message,true)}finally{e.currentTarget.value=''}
  });

  const cropModal=$('[data-fw-crop-modal]'),cropCanvas=$('[data-fw-crop-canvas]'),cropEmpty=$('[data-fw-crop-empty]'),cropCtx=cropCanvas?.getContext('2d');
  const cropSettings={aspect:'4:5',bg:'#171513',scale:1,x:0,y:0};
  function cropDimensions(){
    const [a,b]=String(cropSettings.aspect||'4:5').split(':').map(Number);const max=1000;
    return a>=b?{w:max,h:Math.round(max*b/a)}:{w:Math.round(max*a/b),h:max};
  }
  function syncCropControls(){
    const map=[['aspect','[data-crop-aspect]'],['bg','[data-crop-bg]'],['scale','[data-crop-scale]'],['x','[data-crop-x]'],['y','[data-crop-y]']];
    map.forEach(([k,s])=>{const el=$(s);if(el)el.value=cropSettings[k]});
    $('[data-crop-scale-out]').textContent=`${Math.round(cropSettings.scale*100)}%`;$('[data-crop-x-out]').textContent=String(cropSettings.x);$('[data-crop-y-out]').textContent=String(cropSettings.y);
  }
  function drawCrop(){
    if(!cropCtx||!cropCanvas)return;const {w,h}=cropDimensions();cropCanvas.width=w;cropCanvas.height=h;const ctx=cropCtx;ctx.clearRect(0,0,w,h);ctx.fillStyle=cropSettings.bg;ctx.fillRect(0,0,w,h);
    const img=state.cropImage;if(img){const base=Math.max(w/img.naturalWidth,h/img.naturalHeight)*Number(cropSettings.scale||1);const iw=img.naturalWidth*base,ih=img.naturalHeight*base,x=(w-iw)/2+Number(cropSettings.x||0),y=(h-ih)/2+Number(cropSettings.y||0);ctx.drawImage(img,x,y,iw,ih)}
    cropEmpty?.classList.toggle('hidden',!!img);
  }
  async function loadImage(src){
    const img=new Image();img.decoding='async';await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(Error('Seeker could not load that artwork.'));img.src=src});return img;
  }
  async function openCropMaker(){
    cropModal?.classList.remove('hidden');cropModal?.setAttribute('aria-hidden','false');Object.assign(cropSettings,{scale:1,x:0,y:0});syncCropControls();
    try{const src=await ensureEditableArt();state.cropImage=await loadImage(src);drawCrop()}catch(err){state.cropImage=null;drawCrop();toast(err.message,true)}
  }
  $('[data-fw-art-crop]')?.addEventListener('click',openCropMaker);
  $$('[data-fw-crop-close]').forEach(b=>b.addEventListener('click',()=>{cropModal?.classList.add('hidden');cropModal?.setAttribute('aria-hidden','true')}));
  cropModal?.addEventListener('click',e=>{if(e.target===cropModal){cropModal.classList.add('hidden');cropModal.setAttribute('aria-hidden','true')}});
  const cropControlMap={'[data-crop-aspect]':'aspect','[data-crop-bg]':'bg','[data-crop-scale]':'scale','[data-crop-x]':'x','[data-crop-y]':'y'};
  Object.entries(cropControlMap).forEach(([selector,key])=>$(selector)?.addEventListener('input',e=>{cropSettings[key]=['scale','x','y'].includes(key)?Number(e.currentTarget.value):e.currentTarget.value;syncCropControls();drawCrop()}));
  $('[data-crop-reset]')?.addEventListener('click',()=>{Object.assign(cropSettings,{scale:1,x:0,y:0});syncCropControls();drawCrop()});
  $('[data-crop-save]')?.addEventListener('click',async()=>{
    if(!state.cropImage)return toast('Load artwork first.',true);
    try{const blob=await new Promise((resolve,reject)=>cropCanvas.toBlob(b=>b?resolve(b):reject(Error('Could not render crop.')),'image/webp',.9));const file=new File([blob],`${(fieldValue('title')||'entry').replace(/[^a-z0-9_-]+/gi,'-')}-portrait.webp`,{type:'image/webp'});const out=await uploadFoundryAsset(file,'art');setField('img',out.url);updateArtStatus(out);renderPreview();setDirty();cropModal.classList.add('hidden');cropModal.setAttribute('aria-hidden','true');toast('Cropped portrait saved and assigned.')}catch(err){toast(err.message||'Could not save crop.',true)}
  });

  const tokenModal=$('[data-fw-token-modal]'),tokenCanvas=$('[data-fw-token-canvas]'),tokenEmpty=$('[data-fw-token-empty]');
  const tokenCtx=tokenCanvas?.getContext('2d');
  const tokenFrameDefaults={shape:'circle',ring:'#b79661',bg:'#171513',accent:'#e3c68f',width:30,shadow:true,double:true,glow:false,innerRing:false,pattern:'clean',lineStyle:'solid',vignette:18,brightness:100,saturation:100};
  const tokenSettings={...tokenFrameDefaults,scale:1,x:0,y:0};
  const tokenPresets={
    classic:{ring:'#b79661',bg:'#171513',accent:'#e3c68f',width:30,shape:'circle',double:true,pattern:'clean',lineStyle:'solid',vignette:18,glow:false},
    silver:{ring:'#aeb4bb',bg:'#17191b',accent:'#eef2f4',width:30,shape:'circle',double:true,pattern:'clean',vignette:16},
    bronze:{ring:'#9d6337',bg:'#20150f',accent:'#e3a867',width:36,shape:'circle',double:true,pattern:'rivets',vignette:25},
    iron:{ring:'#666d73',bg:'#17191b',accent:'#c7ccd0',width:34,shape:'circle',double:true,pattern:'rivets',vignette:24},
    obsidian:{ring:'#202126',bg:'#050506',accent:'#6c6d78',width:42,shape:'circle',double:true,pattern:'segmented',vignette:42},
    crimson:{ring:'#7b181a',bg:'#1e0c0d',accent:'#df9b79',width:35,shape:'circle',double:true,pattern:'ticks',vignette:30},
    infernal:{ring:'#84280d',bg:'#180705',accent:'#ff8d38',width:38,shape:'hex',double:true,pattern:'runes',vignette:38,glow:true},
    blood:{ring:'#5d0710',bg:'#130608',accent:'#c73845',width:44,shape:'circle',double:false,pattern:'segmented',lineStyle:'dash',vignette:46},
    arcane:{ring:'#51428f',bg:'#111127',accent:'#a99cf4',width:32,shape:'circle',double:true,pattern:'runes',vignette:25,glow:true},
    occult:{ring:'#512f61',bg:'#120d18',accent:'#d195e5',width:34,shape:'octagon',double:true,pattern:'runes',vignette:32,glow:true},
    divine:{ring:'#d0ad55',bg:'#201b0d',accent:'#fff0a7',width:30,shape:'circle',double:true,pattern:'cardinal',vignette:12,glow:true},
    primal:{ring:'#567843',bg:'#10190d',accent:'#b8dc8f',width:36,shape:'hex',double:true,pattern:'ticks',vignette:24},
    fey:{ring:'#8160a1',bg:'#171020',accent:'#d8b7f3',width:26,shape:'circle',double:true,pattern:'runes',lineStyle:'dot',vignette:15,glow:true},
    nature:{ring:'#49613c',bg:'#11190e',accent:'#accb83',width:34,shape:'circle',double:true,pattern:'ticks',vignette:26},
    poison:{ring:'#647a22',bg:'#101406',accent:'#c3e75d',width:31,shape:'hex',double:true,pattern:'segmented',vignette:34,glow:true},
    undead:{ring:'#514f58',bg:'#0b0a0d',accent:'#a6d6bf',width:38,shape:'octagon',double:true,pattern:'runes',vignette:45},
    frost:{ring:'#8eb9cf',bg:'#0c171d',accent:'#e1f7ff',width:28,shape:'hex',double:true,pattern:'cardinal',vignette:20,glow:true,saturation:88},
    sea:{ring:'#39778a',bg:'#07181d',accent:'#8bd6e6',width:30,shape:'circle',double:true,pattern:'ticks',vignette:22},
    storm:{ring:'#596477',bg:'#0d1018',accent:'#a6c7ff',width:34,shape:'octagon',double:true,pattern:'segmented',lineStyle:'dash',vignette:30,glow:true},
    sun:{ring:'#d38c24',bg:'#251405',accent:'#ffd781',width:34,shape:'circle',double:true,pattern:'cardinal',vignette:14,glow:true,brightness:108},
    moon:{ring:'#7e87a9',bg:'#0e1020',accent:'#dbe1ff',width:28,shape:'circle',double:true,pattern:'runes',vignette:28,glow:true,saturation:78},
    royal:{ring:'#b18b2b',bg:'#1d1026',accent:'#e4c96d',width:40,shape:'shield',double:true,pattern:'rivets',vignette:30},
    construct:{ring:'#75644c',bg:'#15130f',accent:'#bca786',width:46,shape:'octagon',double:true,pattern:'rivets',vignette:18,saturation:75},
    dragon:{ring:'#9a6d30',bg:'#1b0f08',accent:'#e9bc6b',width:44,shape:'hex',double:true,pattern:'ticks',vignette:38},
    parchment:{ring:'#8c704a',bg:'#312516',accent:'#d7bd8b',width:24,shape:'roundsquare',double:true,pattern:'cardinal',vignette:24,saturation:72,brightness:108},
    etched:{ring:'#777c82',bg:'#101214',accent:'#cfd4d8',width:38,shape:'octagon',double:true,pattern:'runes',lineStyle:'solid',vignette:30,saturation:65},
    rune:{ring:'#7355a6',bg:'#0c0712',accent:'#d0a9ff',width:36,shape:'circle',double:true,pattern:'runes',lineStyle:'dash',vignette:36,glow:true},
    boss:{ring:'#b22e2e',bg:'#110707',accent:'#f2c54f',width:55,shape:'octagon',double:true,pattern:'rivets',vignette:48,glow:true,innerRing:true},
    minimal:{ring:'#d5d0c6',bg:'#161616',accent:'#d5d0c6',width:12,shape:'circle',double:false,pattern:'clean',vignette:8},
    portrait:{ring:'#b79661',bg:'#171513',accent:'#e3c68f',width:22,shape:'roundsquare',double:true,pattern:'clean',vignette:12},
    badge:{ring:'#6f7883',bg:'#111419',accent:'#c8d0d8',width:32,shape:'shield',double:true,pattern:'cardinal',vignette:25},
    borderless:{ring:'#000000',bg:'#151515',accent:'#000000',width:0,shape:'circle',double:false,pattern:'clean',vignette:18},
  };
  function tokenPath(ctx,shape,inset=36){
    const s=720,cx=s/2,cy=s/2,r=s/2-inset;ctx.beginPath();
    if(shape==='roundsquare'){const x=inset,y=inset,w=s-inset*2,rad=72;ctx.roundRect(x,y,w,w,rad)}
    else if(shape==='square'){ctx.rect(inset,inset,s-inset*2,s-inset*2)}
    else if(shape==='hex'||shape==='octagon'){const sides=shape==='hex'?6:8;for(let i=0;i<sides;i++){const a=-Math.PI/2+i*Math.PI*2/sides,x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r;i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.closePath()}
    else if(shape==='diamond'){ctx.moveTo(cx,inset);ctx.lineTo(s-inset,cy);ctx.lineTo(cx,s-inset);ctx.lineTo(inset,cy);ctx.closePath()}
    else if(shape==='shield'){ctx.moveTo(cx,inset);ctx.lineTo(s-inset,inset+70);ctx.lineTo(s-inset-35,cy+115);ctx.quadraticCurveTo(cx, s-inset, cx, s-inset);ctx.quadraticCurveTo(inset+35,cy+115,inset,inset+70);ctx.closePath()}
    else ctx.arc(cx,cy,r,0,Math.PI*2);
  }
  function drawTokenPattern(ctx,settings){
    const s=720,cx=360,cy=360,r=360-36-Math.max(6,Number(settings.width||0)*.55);const color=settings.accent;ctx.save();ctx.strokeStyle=color;ctx.fillStyle=color;ctx.globalAlpha=.8;ctx.lineWidth=4;
    const pattern=settings.pattern||'clean';
    if(pattern==='ticks'||pattern==='cardinal'||pattern==='runes'||pattern==='rivets'){
      const count=pattern==='cardinal'?4:pattern==='rivets'?12:pattern==='runes'?16:24;
      for(let i=0;i<count;i++){const a=-Math.PI/2+i*Math.PI*2/count;const x1=cx+Math.cos(a)*(r-3),y1=cy+Math.sin(a)*(r-3);const x2=cx+Math.cos(a)*(r-(pattern==='runes'?16:pattern==='cardinal'?22:10)),y2=cy+Math.sin(a)*(r-(pattern==='runes'?16:pattern==='cardinal'?22:10));if(pattern==='rivets'){ctx.beginPath();ctx.arc(x1,y1,5,0,Math.PI*2);ctx.fill()}else{ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();if(pattern==='runes'&&i%2===0){ctx.beginPath();ctx.arc(x2,y2,3,0,Math.PI*2);ctx.fill()}}}
    }
    ctx.restore();
  }
  function syncTokenControls(){
    const map=[['shape','[data-token-shape]'],['pattern','[data-token-pattern]'],['lineStyle','[data-token-line-style]'],['ring','[data-token-ring]'],['bg','[data-token-bg]'],['accent','[data-token-accent]'],['scale','[data-token-scale]'],['x','[data-token-x]'],['y','[data-token-y]'],['width','[data-token-width]'],['vignette','[data-token-vignette]'],['brightness','[data-token-brightness]'],['saturation','[data-token-saturation]']];
    map.forEach(([k,s])=>{const el=$(s);if(el)el.value=tokenSettings[k]});
    const checks=[['shadow','[data-token-shadow]'],['double','[data-token-double]'],['glow','[data-token-glow]'],['innerRing','[data-token-inner-ring]']];checks.forEach(([k,s])=>{const el=$(s);if(el)el.checked=!!tokenSettings[k]});
    $('[data-token-scale-out]').textContent=`${Math.round(tokenSettings.scale*100)}%`;$('[data-token-x-out]').textContent=String(tokenSettings.x);$('[data-token-y-out]').textContent=String(tokenSettings.y);$('[data-token-width-out]').textContent=String(tokenSettings.width);$('[data-token-vignette-out]').textContent=String(tokenSettings.vignette);$('[data-token-brightness-out]').textContent=`${tokenSettings.brightness}%`;$('[data-token-saturation-out]').textContent=`${tokenSettings.saturation}%`;
  }
  function drawToken(){
    if(!tokenCtx||!tokenCanvas)return;const ctx=tokenCtx,s=720;ctx.clearRect(0,0,s,s);
    tokenPath(ctx,tokenSettings.shape,36);ctx.save();ctx.clip();ctx.fillStyle=tokenSettings.bg;ctx.fillRect(0,0,s,s);
    const img=state.tokenImage;if(img){const base=Math.max(s/img.naturalWidth,s/img.naturalHeight)*Number(tokenSettings.scale||1);const w=img.naturalWidth*base,h=img.naturalHeight*base,x=(s-w)/2+Number(tokenSettings.x||0),y=(s-h)/2+Number(tokenSettings.y||0);ctx.filter=`brightness(${Number(tokenSettings.brightness||100)}%) saturate(${Number(tokenSettings.saturation||100)}%)`;ctx.drawImage(img,x,y,w,h);ctx.filter='none'}
    const vig=Math.max(0,Math.min(100,Number(tokenSettings.vignette||0)))/100;if(vig>0){const g=ctx.createRadialGradient(360,340,170,360,360,360);g.addColorStop(.45,'rgba(0,0,0,0)');g.addColorStop(1,`rgba(0,0,0,${Math.min(.82,vig)})`);ctx.fillStyle=g;ctx.fillRect(0,0,s,s)}ctx.restore();
    const width=Number(tokenSettings.width||0);if(width>0){ctx.save();if(tokenSettings.shadow){ctx.shadowColor='rgba(0,0,0,.72)';ctx.shadowBlur=22;ctx.shadowOffsetY=10}if(tokenSettings.glow){ctx.shadowColor=tokenSettings.accent;ctx.shadowBlur=26;ctx.shadowOffsetY=0}tokenPath(ctx,tokenSettings.shape,36+width/2);ctx.strokeStyle=tokenSettings.ring;ctx.lineWidth=width;if(tokenSettings.lineStyle==='dash')ctx.setLineDash([28,14]);else if(tokenSettings.lineStyle==='dot')ctx.setLineDash([3,13]);else if(tokenSettings.pattern==='segmented')ctx.setLineDash([48,10]);ctx.stroke();ctx.restore();if(tokenSettings.double&&width>8){tokenPath(ctx,tokenSettings.shape,36+width+8);ctx.strokeStyle=tokenSettings.accent;ctx.lineWidth=Math.max(3,width*.14);ctx.setLineDash([]);ctx.stroke()}if(tokenSettings.innerRing){tokenPath(ctx,tokenSettings.shape,Math.max(8,36-width*.08));ctx.strokeStyle=tokenSettings.accent;ctx.globalAlpha=.85;ctx.lineWidth=3;ctx.stroke();ctx.globalAlpha=1}drawTokenPattern(ctx,tokenSettings)}
    tokenEmpty?.classList.toggle('hidden',!!img);
  }
  async function loadTokenSource(src){
    if(!src)throw Error('Add portrait artwork first.');
    const img=await loadImage(src);state.tokenImage=img;drawToken();
  }
  let tokenRecipes=[];
  function tokenRecipeSettings(){
    const out={};for(const key of Object.keys(tokenFrameDefaults))out[key]=tokenSettings[key];return out;
  }
  function renderTokenRecipes(){
    const sel=$('[data-token-recipe-select]');if(!sel)return;const chosen=sel.value;
    sel.innerHTML='<option value="">Choose saved recipe…</option>'+tokenRecipes.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('');
    if(tokenRecipes.some(r=>String(r.id)===String(chosen)))sel.value=chosen;
  }
  async function loadTokenRecipes(){try{tokenRecipes=await jsonFetch('/api/v7/token-recipes',{cache:'no-store'});renderTokenRecipes()}catch{tokenRecipes=[];renderTokenRecipes()}}
  async function openTokenMaker(){
    tokenModal?.classList.remove('hidden');tokenModal?.setAttribute('aria-hidden','false');syncTokenControls();loadTokenRecipes();
    try{const src=await ensureEditableArt();await loadTokenSource(src)}catch(err){state.tokenImage=null;drawToken();toast(err.message,true)}
  }
  $('[data-fw-token-maker]')?.addEventListener('click',openTokenMaker);$('[data-fw-token-close]')?.addEventListener('click',()=>{tokenModal?.classList.add('hidden');tokenModal?.setAttribute('aria-hidden','true')});tokenModal?.addEventListener('click',e=>{if(e.target===tokenModal){tokenModal.classList.add('hidden');tokenModal.setAttribute('aria-hidden','true')}});
  $$('[data-token-preset]').forEach(b=>b.addEventListener('click',()=>{const position={scale:tokenSettings.scale,x:tokenSettings.x,y:tokenSettings.y};Object.assign(tokenSettings,tokenFrameDefaults,tokenPresets[b.dataset.tokenPreset]||{},position);syncTokenControls();drawToken();$$('[data-token-preset]').forEach(x=>x.classList.toggle('active',x===b))}));
  const tokenControlMap={'[data-token-shape]':'shape','[data-token-pattern]':'pattern','[data-token-line-style]':'lineStyle','[data-token-ring]':'ring','[data-token-bg]':'bg','[data-token-accent]':'accent','[data-token-scale]':'scale','[data-token-x]':'x','[data-token-y]':'y','[data-token-width]':'width','[data-token-vignette]':'vignette','[data-token-brightness]':'brightness','[data-token-saturation]':'saturation'};
  Object.entries(tokenControlMap).forEach(([selector,key])=>$(selector)?.addEventListener('input',e=>{tokenSettings[key]=['scale','x','y','width','vignette','brightness','saturation'].includes(key)?Number(e.currentTarget.value):e.currentTarget.value;syncTokenControls();drawToken()}));
  $('[data-token-shadow]')?.addEventListener('change',e=>{tokenSettings.shadow=e.currentTarget.checked;drawToken()});$('[data-token-double]')?.addEventListener('change',e=>{tokenSettings.double=e.currentTarget.checked;drawToken()});$('[data-token-glow]')?.addEventListener('change',e=>{tokenSettings.glow=e.currentTarget.checked;drawToken()});$('[data-token-inner-ring]')?.addEventListener('change',e=>{tokenSettings.innerRing=e.currentTarget.checked;drawToken()});
  $('[data-token-reset]')?.addEventListener('click',()=>{Object.assign(tokenSettings,tokenFrameDefaults,tokenPresets.classic,{scale:1,x:0,y:0});syncTokenControls();drawToken()});
  $('[data-token-recipe-apply]')?.addEventListener('click',()=>{const id=$('[data-token-recipe-select]')?.value,r=tokenRecipes.find(x=>String(x.id)===String(id));if(!r)return toast('Choose a saved recipe first.',true);const position={scale:tokenSettings.scale,x:tokenSettings.x,y:tokenSettings.y};Object.assign(tokenSettings,tokenFrameDefaults,r.settings||{},position);syncTokenControls();drawToken();toast(`Applied ${r.name}.`)});
  $('[data-token-recipe-save]')?.addEventListener('click',async()=>{const name=$('[data-token-recipe-name]')?.value.trim();if(!name)return toast('Give this recipe a name.',true);try{const r=await send('/api/v7/token-recipes','POST',{name,description:`Saved from Token Forge for ${fieldValue('title')||'campaign art'}`,settings:tokenRecipeSettings()});tokenRecipes=[...tokenRecipes.filter(x=>x.name!==r.name),r].sort((a,b)=>a.name.localeCompare(b.name));renderTokenRecipes();$('[data-token-recipe-select]').value=String(r.id);$('[data-token-recipe-name]').value='';toast('Token recipe saved for this campaign.')}catch(err){toast(err.message,true)}});
  $('[data-token-recipe-delete]')?.addEventListener('click',async()=>{const id=$('[data-token-recipe-select]')?.value,r=tokenRecipes.find(x=>String(x.id)===String(id));if(!r)return toast('Choose a saved recipe first.',true);try{await jsonFetch(`/api/v7/token-recipes/${id}`,{method:'DELETE'});tokenRecipes=tokenRecipes.filter(x=>String(x.id)!==String(id));renderTokenRecipes();toast('Token recipe deleted.')}catch(err){toast(err.message,true)}});
  $('[data-token-source-file]')?.addEventListener('change',async e=>{const file=e.currentTarget.files?.[0];if(!file)return;try{const out=await uploadFoundryAsset(file,'art');setField('img',out.url);updateArtStatus(out);await loadTokenSource(out.url);renderPreview();setDirty();toast('New token source optimized and loaded.')}catch(err){toast(err.message,true)}finally{e.currentTarget.value=''}});
  $('[data-token-save]')?.addEventListener('click',async()=>{
    if(!state.tokenImage)return toast('Load artwork first.',true);
    try{
      const blob=await new Promise((resolve,reject)=>{try{tokenCanvas.toBlob(b=>b?resolve(b):reject(Error('Could not render token.')),'image/webp',.92)}catch{reject(Error('Could not export this token.'))}});
      const file=new File([blob],`${(fieldValue('title')||'creature').replace(/[^a-z0-9_-]+/gi,'-')}-token.webp`,{type:'image/webp'});const out=await uploadFoundryAsset(file,'token');setField('token_img',out.url);setDirty();toast('Token optimized, saved, and assigned.');tokenModal.classList.add('hidden');tokenModal.setAttribute('aria-hidden','true');
    }catch(err){toast(err.message||'Could not save token.',true)}
  });

  function switchMobile(view){root.querySelector('.fw-workspace')?.setAttribute('data-fw-mobile-view',view);$$('[data-fw-mobile]').forEach(b=>b.classList.toggle('active',b.dataset.fwMobile===view))}
  $$('[data-fw-mobile]').forEach(b=>b.addEventListener('click',()=>switchMobile(b.dataset.fwMobile)));

  // Restore only a genuinely unsaved local draft. Saved Seeker entries always win.
  let draft=null;try{draft=JSON.parse(localStorage.getItem('seeker-foundry-workshop-draft')||'null')}catch{}
  if(draft && !draft.id && (draft.title||draft.summary||draft.payload?.description)){fillForm(draft);state.currentId=null;state.savedSnapshot='';setDirty()}else{fillForm()}
  renderLibrary();renderLog();renderPreview();
})();
