(()=>{
  const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
  const toast=(msg,bad=false)=>{let n=$('#homebrewToast');if(!n){n=document.createElement('div');n.id='homebrewToast';n.className='v6-toast';document.body.appendChild(n)}n.textContent=msg;n.classList.toggle('bad',bad);n.classList.add('show');clearTimeout(n._t);n._t=setTimeout(()=>n.classList.remove('show'),3800)};
  const api=async(url,opt={})=>{const r=await fetch(url,{cache:'no-store',...opt});const body=await r.json().catch(()=>({}));if(!r.ok)throw Error(body.detail||body.message||`Request failed (${r.status})`);return body};
  const send=(url,method,body)=>api(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let section='all',query='',featCategory='all';
  function applyFilters(){
    const featFilter=$('[data-homebrew-feat-filter]');if(featFilter)featFilter.hidden=section!=='feats';
    $$('[data-homebrew-section]').forEach(sec=>{
      const indexOnly=sec.dataset.homebrewIndex==='true';
      const sectionMatch=section==='all'?!indexOnly:sec.dataset.homebrewSection===section;let any=false;
      $$('[data-homebrew-entry]',sec).forEach(card=>{const searchHit=!query||String(card.dataset.search||'').includes(query),cat=card.dataset.featCategoryCard||'',catHit=section!=='feats'||featCategory==='all'||cat===featCategory,hit=searchHit&&catHit;card.hidden=!hit;if(hit)any=true});
      $$('[data-feat-category-group]',sec).forEach(group=>{const categoryHit=featCategory==='all'||group.dataset.featCategoryGroup===featCategory;const visible=[...group.querySelectorAll('[data-homebrew-entry]')].some(x=>!x.hidden);group.hidden=!categoryHit||!visible});
      sec.hidden=!sectionMatch||((query||section==='feats')&&!any);
    });
  }
  $('[data-homebrew-search]')?.addEventListener('input',e=>{query=e.currentTarget.value.trim().toLowerCase();applyFilters()});
  $$('[data-homebrew-filter] button').forEach(b=>b.addEventListener('click',()=>{section=b.dataset.section;$$('[data-homebrew-filter] button').forEach(x=>x.classList.toggle('active',x===b));applyFilters()}));
  $$('[data-homebrew-feat-filter] button').forEach(b=>b.addEventListener('click',()=>{featCategory=b.dataset.featCategory||'all';$$('[data-homebrew-feat-filter] button').forEach(x=>x.classList.toggle('active',x===b));applyFilters()}));
  applyFilters();

  async function sourceFoundry(button){button.disabled=true;try{const out=await send(`/api/homebrew/source/${encodeURIComponent(button.dataset.homebrewSourceFoundry)}/foundry`,'POST',{});const label=out.section==='ancestry'?'Ancestry bundle':'Homebrew bundle';toast(`${label} queued · ${out.rules||0} detected rule${out.rules===1?'':'s'} · command #${out.command?.id||'—'}`)}catch(e){toast(e.message,true)}finally{button.disabled=false}}
  $$('[data-homebrew-source-foundry]').forEach(b=>b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();sourceFoundry(b)}));

  const dataEl=$('#homebrewData');if(!dataEl)return;
  let sections=[];try{sections=JSON.parse(dataEl.textContent||'[]')}catch{}
  const entries=[];sections.forEach(sec=>(sec.groups||[]).forEach(g=>(g.entries||[]).forEach(e=>entries.push(e))));
  const byId=id=>entries.find(e=>String(e.id)===String(id));
  const dlg=$('[data-homebrew-dialog]'),form=$('[data-homebrew-form]');let current=null;
  const field=n=>form?.elements?.namedItem(n);
  const set=(n,v)=>{const el=field(n);if(!el)return;if(el.type==='checkbox')el.checked=!!v;else el.value=v??''};
  function openEdit(id,placement=false){const e=byId(id);if(!e)return;current=e;const p=e.payload||{},m=e.library||{};$('[data-homebrew-dialog-title]').textContent=e.title||'Entry';set('title',e.title);set('level',p.level??m.level??0);set('kind',e.kind||m.effective_kind||'homebrew');set('homebrew_publish',!!m.published);set('traits',p.traits||e.tags||'');set('subtitle',e.subtitle||'');set('library_section',p.library_section||'auto');set('library_group',p.library_group||'');set('ancestry_trait',p.ancestry_trait||'');set('archetype_name',p.archetype_name||'');set('class_name',p.class_name||'');set('feat_category',p.feat_category||'general');set('action_cost',p.action_cost||p.homebrew_actions||'');set('frequency',p.frequency||p.homebrew_frequency||'');set('access',p.access||'');set('prerequisites',p.prerequisites||'');set('trigger',p.trigger||p.homebrew_trigger||'');set('requirements',p.requirements||'');set('special',p.special||'');set('description',p.description||'');set('summary',e.summary||'');dlg.showModal?.();if(placement)setTimeout(()=>$('.homebrew-placement select',dlg)?.focus(),50)}
  $$('[data-homebrew-edit]').forEach(b=>b.addEventListener('click',()=>openEdit(b.dataset.homebrewEdit)));
  $$('[data-homebrew-move]').forEach(b=>b.addEventListener('click',()=>openEdit(b.dataset.homebrewMove,true)));
  $$('[data-homebrew-close]').forEach(b=>b.addEventListener('click',()=>dlg.close?.()));
  form?.addEventListener('submit',async ev=>{ev.preventDefault();if(!current)return;const fd=new FormData(form),p={...(current.payload||{})};['level','traits','library_section','library_group','ancestry_trait','archetype_name','class_name','feat_category','action_cost','frequency','access','prerequisites','trigger','requirements','special','description'].forEach(k=>{let v=fd.get(k);if(k==='level')v=Number(v||0);p[k]=v??''});p.homebrew_publish=fd.has('homebrew_publish');if(String(fd.get('kind'))==='action')p.homebrew_document='action';try{await send(`/api/homebrew/${current.id}`,'PUT',{kind:String(fd.get('kind')||current.kind),title:String(fd.get('title')||'').trim(),subtitle:String(fd.get('subtitle')||''),summary:String(fd.get('summary')||''),tags:String(fd.get('traits')||''),payload:p});toast('Homebrew updated.');setTimeout(()=>location.reload(),350)}catch(e){toast(e.message,true)}});

  async function worldPush(id,button){button.disabled=true;try{const out=await send(`/api/v61/foundry/content/${id}/push`,'POST',{target_type:'world'});toast(`Queued for Foundry Items · command #${out.command?.id||'—'}`)}catch(e){toast(e.message,true)}finally{button.disabled=false}}
  $$('[data-homebrew-world]').forEach(b=>b.addEventListener('click',()=>worldPush(b.dataset.homebrewWorld,b)));
  $$('[data-homebrew-delete]').forEach(b=>b.addEventListener('click',async()=>{const e=byId(b.dataset.homebrewDelete);if(!confirm(`Delete ${e?.title||'this homebrew entry'} from Seeker?\n\nThis deletes the Homebrew Forge source. It does not delete copies already in Foundry or LaTeX.`))return;try{await api(`/api/homebrew/${b.dataset.homebrewDelete}`,{method:'DELETE'});b.closest('[data-homebrew-entry]')?.remove();toast('Homebrew entry deleted.')}catch(e){toast(e.message,true)}}));

  const giveDlg=$('[data-homebrew-give-dialog]');let giveId=null;
  $$('[data-homebrew-give]').forEach(b=>b.addEventListener('click',()=>{giveId=b.dataset.homebrewGive;giveDlg.showModal?.()}));
  $('[data-homebrew-give-close]')?.addEventListener('click',()=>giveDlg.close?.());
  $('[data-homebrew-give-confirm]')?.addEventListener('click',async e=>{if(!giveId)return;const actor=$('[data-homebrew-actor]')?.value;if(!actor)return toast('Choose an actor.',true);e.currentTarget.disabled=true;try{const out=await send(`/api/v61/foundry/content/${giveId}/push`,'POST',{target_type:'actor',actor_id:actor});giveDlg.close?.();toast(`Item delivery queued · command #${out.command?.id||'—'}`)}catch(err){toast(err.message,true)}finally{e.currentTarget.disabled=false}});

  const latexDlg=$('[data-homebrew-latex-dialog]'),latexText=$('[data-homebrew-latex-text]'),latexPath=$('[data-homebrew-latex-path]'),latexHeading=$('[data-homebrew-latex-heading]');let latexId=null,latexTargets=[];
  const targetForPath=()=>latexTargets.find(x=>x.path===latexPath.value);
  function renderHeadingOptions(selected=null){const target=targetForPath();const rows=target?.headings||[];latexHeading.innerHTML='<option value="">End of file</option>'+rows.map(h=>{const key=JSON.stringify([h.level,h.title,h.index]);const indent={'part':'','chapter':'','section':'— ','subsection':'—— ','subsubsection':'——— '}[h.level]||'';return `<option value="${esc(key)}">${esc(indent+h.title)} · ${esc(h.level)}</option>`}).join('');if(selected?.title){const wanted=JSON.stringify([selected.level,selected.title,Number(selected.index||0)]);if([...latexHeading.options].some(o=>o.value===wanted))latexHeading.value=wanted}}
  latexPath?.addEventListener('change',()=>renderHeadingOptions());
  $$('[data-homebrew-latex]').forEach(b=>b.addEventListener('click',async()=>{try{const out=await api(`/api/homebrew/${b.dataset.homebrewLatex}/latex`);latexId=out.id;latexText.value=out.snippet||'';latexTargets=Array.isArray(out.targets)?out.targets:[];const known=new Set(latexTargets.map(x=>x.path));if(out.suggested_path&&!known.has(out.suggested_path))latexTargets.unshift({path:out.suggested_path,headings:[]});latexPath.innerHTML=latexTargets.map(t=>`<option value="${esc(t.path)}">${esc(t.path)}${known.has(t.path)?'':' · new'}</option>`).join('');latexPath.value=out.suggested_path||latexTargets[0]?.path||'';renderHeadingOptions(out.selected_heading||null);latexDlg.showModal?.()}catch(e){toast(e.message,true)}}));
  $('[data-homebrew-latex-close]')?.addEventListener('click',()=>latexDlg.close?.());
  $('[data-homebrew-copy-latex]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(latexText.value);toast('LaTeX copied.')}catch{toast('Clipboard permission was denied.',true)}});
  $('[data-homebrew-write-latex]')?.addEventListener('click',async e=>{if(!latexId)return;const path=latexPath.value.trim();if(!path)return toast('Choose a .tex path.',true);let heading={level:'',title:'',index:0};if(latexHeading.value){try{const [level,title,index]=JSON.parse(latexHeading.value);heading={level,title,index:Number(index||0)}}catch{}}e.currentTarget.disabled=true;try{const out=await send(`/api/homebrew/${latexId}/latex/write`,'POST',{path,snippet:latexText.value,heading_level:heading.level,heading_title:heading.title,heading_index:heading.index});latexDlg.close?.();toast(out.duplicate_detected?'Existing same-name LaTeX rule found and linked; no duplicate was added.':out.wiki_warning?'LaTeX written; Codex rebuild reported a warning.':'LaTeX written and Codex rebuilt.')}catch(err){toast(err.message,true)}finally{e.currentTarget.disabled=false}});
})();
