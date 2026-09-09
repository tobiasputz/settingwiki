(()=>{
  const role=(document.body.dataset.adminView==='true'||location.pathname.startsWith('/admin')||location.pathname.startsWith('/gm/'))?'gm':'player';
  const key=`loreforge.quickTour.v4.${role}`;
  const visible=el=>!!el&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden';
  const firstVisible=selector=>[...document.querySelectorAll(selector)].find(visible)||null;
  const commonPlayer=[
    {selector:'.brand',title:'Welcome to Loreforge',body:'This is your campaign companion: known lore, session memory, characters, maps, mysteries, and everything your GM has revealed.'},
    {selector:'[data-tour-target="session"],[data-mobile-nav="session"]',title:'Use Session at the table',body:'Open this during play for the live location, spotlight lore, handouts, new discoveries, mysteries, and your notes.'},
    {selector:'[data-session-character-panel],[data-session-character-open]',title:'Enter as your character',body:'If you play more than one character, choose who you are playing tonight. Your private session notes stay attached to that character.'},
    {selector:'[data-tour-target="campaign"],[data-mobile-nav="campaign"]',title:'Your campaign memory',body:'Campaign is the party desk for plot threads, journals, rumors, character arcs, and the world state you are allowed to know.'},
    {selector:'[data-tour-target="characters"],a[href="/characters"]',title:'Keep character dossiers here',body:'Your character pages hold biography, goals, arcs, relationships, portraits, and inspiration art.'},
    {selector:'[data-tour-target="search"],[data-open-search]',title:'Jump anywhere fast',body:'Search lore and tools from anywhere. On a keyboard, press / or Ctrl/⌘ K; on phones, use the Search tab.'},
    {selector:'[data-tour-target="explore"],[data-mobile-more]',title:'Everything else lives under Explore',body:'History, calendar, mysteries, handouts, lore connections, families and orders are grouped here so the main bar stays calm.'},
    {selector:'[data-tour-target="notifications"]',title:'Watch for GM reveals',body:'The star shows campaign notifications and live spotlight pushes without making you reload pages manually.'},
  ];
  const gmSteps=[
    {selector:'.brand,.studio-brand,.campaign-control-header,.gm-session-topbar',title:'Loreforge 4',body:'The player-facing site stays uncluttered, while GM tools are grouped into dedicated modes you can switch between quickly.'},
    {selector:'[data-tour-target="gm-tools"],.admin-mode-dock',title:'GM tools are now grouped',body:'Use GM Session while running the table, Studio for source editing, World for campaign control, and Living for evolving state.'},
    {selector:'#compileBtn',title:'Studio stays source-first',body:'Edit the LaTeX project, compile, inspect the player result, and use the source bridge from Codex entries when you need exact edits.'},
    {selector:'.gm-live-controls,.gm-session-grid',title:'Run the table from Session Mode',body:'Start or update the live session, spotlight lore and maps, push discoveries, reveal handouts, and advance fronts from one screen.'},
    {selector:'.cc-sidebar,.campaign-control-nav',title:'World control is organized by job',body:'Sessions, party, chronology, reveals, mysteries, handouts, atlas layers, health, and snapshots stay separated instead of crowding the player UI.'},
    {selector:'[data-tour-target="search"],[data-open-search]',title:'Search works as a command palette',body:'Use Ctrl/⌘ K or / to jump through lore and common GM destinations without hunting through menus.'},
    {selector:'[data-start-tour]',title:'Replay this whenever you want',body:'The Quick tour button is always available in Explore or the GM mode dock. New players can safely learn the tool without a separate manual.'},
  ];
  let active=false,index=0,steps=[],backdrop,ring,card,currentTarget;
  const clean=()=>{active=false;currentTarget=null;backdrop?.remove();ring?.remove();card?.remove();backdrop=ring=card=null;document.removeEventListener('keydown',onKey);window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true)};
  const done=()=>{try{localStorage.setItem(key,'done')}catch{}clean()};
  const position=()=>{
    if(!active||!currentTarget||!ring||!card)return;
    const r=currentTarget.getBoundingClientRect(),pad=6;
    ring.style.left=Math.max(4,r.left-pad)+'px';ring.style.top=Math.max(4,r.top-pad)+'px';ring.style.width=Math.min(innerWidth-8,r.width+pad*2)+'px';ring.style.height=Math.min(innerHeight-8,r.height+pad*2)+'px';
    if(innerWidth<=640)return;
    const cr=card.getBoundingClientRect(),spaceBelow=innerHeight-r.bottom,top=spaceBelow>cr.height+28?r.bottom+18:Math.max(14,r.top-cr.height-18);let left=Math.min(innerWidth-cr.width-14,Math.max(14,r.left));
    if(r.left>innerWidth*.58)left=Math.max(14,r.right-cr.width);
    card.style.left=left+'px';card.style.top=Math.min(innerHeight-cr.height-14,Math.max(14,top))+'px';
  };
  const render=()=>{
    const step=steps[index];currentTarget=firstVisible(step.selector);
    if(!currentTarget){if(index<steps.length-1){index++;render()}else done();return}
    currentTarget.scrollIntoView({block:'nearest',inline:'nearest',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
    card.innerHTML=`<small>QUICK TOUR · ${role==='gm'?'GM':'PLAYER'}</small><h2>${escapeHtml(step.title)}</h2><p>${escapeHtml(step.body)}</p><div class="lf-tour-actions"><span>${index+1} / ${steps.length}</span><div><button class="lf-tour-skip" type="button">Skip</button>${index?'<button class="lf-tour-back" type="button">Back</button>':''}<button class="lf-tour-next" type="button">${index===steps.length-1?'Finish':'Next'}</button></div></div>`;
    card.querySelector('.lf-tour-skip').onclick=done;card.querySelector('.lf-tour-back')?.addEventListener('click',()=>{index--;render()});card.querySelector('.lf-tour-next').onclick=()=>{if(index===steps.length-1)done();else{index++;render()}};
    requestAnimationFrame(()=>setTimeout(position,40));
  };
  const onKey=e=>{if(e.key==='Escape')done();if(e.key==='ArrowRight'&&active){e.preventDefault();if(index===steps.length-1)done();else{index++;render()}}if(e.key==='ArrowLeft'&&active&&index){e.preventDefault();index--;render()}};
  const start=(force=false)=>{
    if(active)return;if(!force){try{if(localStorage.getItem(key)==='done')return}catch{}}
    const source=role==='gm'?gmSteps:commonPlayer;steps=source.filter(s=>firstVisible(s.selector));if(steps.length<2)return;
    active=true;index=0;backdrop=document.createElement('div');ring=document.createElement('div');card=document.createElement('div');backdrop.className='lf-tour-backdrop';ring.className='lf-tour-ring';card.className='lf-tour-card';card.tabIndex=-1;document.body.append(backdrop,ring,card);backdrop.onclick=()=>{};document.addEventListener('keydown',onKey);window.addEventListener('resize',position);window.addEventListener('scroll',position,true);render();card.focus({preventScroll:true});
  };
  document.addEventListener('click',e=>{if(e.target.closest('[data-start-tour]')){e.preventDefault();document.querySelectorAll('details[open]').forEach(d=>d.removeAttribute('open'));setTimeout(()=>start(true),20)}});
  setTimeout(()=>start(false),700);
  function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
})();
