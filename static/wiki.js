(()=>{
  const overlay=document.getElementById('searchOverlay'), input=document.getElementById('globalSearch'), results=document.getElementById('searchResults');
  let searchItems=[],searchIndex=-1;
  const open=()=>{if(!overlay)return;overlay.classList.add('open');overlay.setAttribute('aria-hidden','false');setTimeout(()=>input?.focus(),40)};
  const close=()=>{overlay?.classList.remove('open');overlay?.setAttribute('aria-hidden','true');searchIndex=-1};
  document.querySelectorAll('[data-open-search]').forEach(b=>b.addEventListener('click',open));
  overlay?.addEventListener('click',e=>{if(e.target===overlay)close()});
  document.addEventListener('keydown',e=>{
    if((e.key==='/'||((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'))&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)){e.preventDefault();open()}
    if(e.key==='Escape')close();
    if(overlay?.classList.contains('open')&&['ArrowDown','ArrowUp','Enter'].includes(e.key)){
      const anchors=[...results.querySelectorAll('.search-result')];if(!anchors.length)return;e.preventDefault();
      if(e.key==='ArrowDown')searchIndex=(searchIndex+1)%anchors.length;
      if(e.key==='ArrowUp')searchIndex=(searchIndex-1+anchors.length)%anchors.length;
      anchors.forEach((a,i)=>a.classList.toggle('selected',i===searchIndex));
      if(e.key==='Enter'&&searchIndex>=0)location.href=anchors[searchIndex].href;
    }
  });
  let timer; input?.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(async()=>{const q=input.value.trim();searchIndex=-1;if(!q){results.innerHTML='<div class="search-hint">Type a place, person, faction, item, or phrase.</div>';return} const data=await fetch('/api/public/search?q='+encodeURIComponent(q)).then(r=>r.json());searchItems=data;results.innerHTML=data.length?data.map(x=>`<a class="search-result" href="${escapeHtml(x.href||('/wiki/'+x.slug))}"><small>${escapeHtml(x.chapter||'Setting')}<span class="search-type">${escapeHtml(x.type||'lore')}</span></small><strong>${escapeHtml(x.title)}</strong><p>${escapeHtml(x.excerpt||'')}</p></a>`).join(''):'<div class="search-hint">No matching lore found.</div>'},160)});

  // Reading progress.
  const progress=document.getElementById('readingProgress'); if(progress){const update=()=>{const h=document.documentElement.scrollHeight-innerHeight;progress.style.width=(h?scrollY/h*100:0)+'%'};addEventListener('scroll',update,{passive:true});update()}
  document.querySelectorAll('time[data-epoch]').forEach(t=>{const d=new Date(Number(t.dataset.epoch)*1000);t.textContent=d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})});
  const io=new IntersectionObserver(entries=>entries.forEach(x=>x.isIntersecting&&x.target.classList.add('visible')),{threshold:.08});document.querySelectorAll('.reveal').forEach(x=>io.observe(x));

  // Codex sidebar state survives full page navigation.  In addition to open
  // groups and scrollTop, remember the clicked row's viewport offset; after the
  // next page expands its active chapter we compensate for that layout change so
  // the navigation visually stays in the same place instead of jumping.
  const sidebar=document.querySelector('[data-sidebar-scroll]');
  if(sidebar){
    const stateKey='loreforge.codex.sidebar.state.v2';
    let state={scrollTop:0,openGroups:[],clickedSlug:'',clickedOffset:null};
    try{state=Object.assign(state,JSON.parse(sessionStorage.getItem(stateKey)||'{}'))}catch(_){}
    const groups=[...sidebar.querySelectorAll('[data-sidebar-group]')];
    const save=extra=>{const next={scrollTop:sidebar.scrollTop,openGroups:groups.filter(g=>g.classList.contains('open')).map(g=>g.dataset.sidebarGroup),clickedSlug:state.clickedSlug||'',clickedOffset:state.clickedOffset};Object.assign(next,extra||{});state=next;sessionStorage.setItem(stateKey,JSON.stringify(next))};
    groups.forEach(group=>{
      const shouldOpen=group.classList.contains('active-group')||(state.openGroups||[]).includes(group.dataset.sidebarGroup);
      group.classList.toggle('open',shouldOpen);const btn=group.querySelector('[data-sidebar-toggle]');btn?.setAttribute('aria-expanded',shouldOpen?'true':'false');
      btn?.addEventListener('click',()=>{group.classList.toggle('open');btn.setAttribute('aria-expanded',group.classList.contains('open')?'true':'false');save()});
    });
    const restore=()=>{
      sidebar.scrollTop=Number(state.scrollTop)||0;
      const active=sidebar.querySelector('[data-codex-entry].active');
      const activeSlug=active?.dataset.entrySlug||'';
      if(active&&state.clickedSlug===activeSlug&&Number.isFinite(Number(state.clickedOffset))){
        const sr=sidebar.getBoundingClientRect(),ar=active.getBoundingClientRect();
        sidebar.scrollTop+=ar.top-sr.top-Number(state.clickedOffset);
      }else if(active&&!state.clickedSlug){
        const sr=sidebar.getBoundingClientRect(),ar=active.getBoundingClientRect();
        if(ar.top<sr.top+45||ar.bottom>sr.bottom-35)active.scrollIntoView({block:'center'});
      }
    };
    requestAnimationFrame(()=>requestAnimationFrame(restore));
    document.fonts?.ready?.then(()=>setTimeout(restore,0)).catch?.(()=>{});
    let saveScroll;sidebar.addEventListener('scroll',()=>{clearTimeout(saveScroll);saveScroll=setTimeout(()=>save(),80)},{passive:true});
    sidebar.querySelectorAll('[data-codex-entry]').forEach(a=>a.addEventListener('click',()=>{const sr=sidebar.getBoundingClientRect(),ar=a.getBoundingClientRect();save({clickedSlug:a.dataset.entrySlug||'',clickedOffset:ar.top-sr.top})}));
    addEventListener('pagehide',()=>save(),{capture:true});
  }

  // Any rendered LaTeX image can be inspected at full resolution.
  const zoomButtons=[...document.querySelectorAll('.lore-image-zoom')];
  if(zoomButtons.length){
    const box=document.createElement('div');box.className='lore-lightbox';box.setAttribute('aria-hidden','true');box.innerHTML='<button type="button" aria-label="Close image">×</button><img alt="">';document.body.appendChild(box);
    const boxImg=box.querySelector('img');
    const closeImage=()=>{box.classList.remove('open');box.setAttribute('aria-hidden','true');boxImg.removeAttribute('src')};
    zoomButtons.forEach(btn=>btn.addEventListener('click',()=>{const img=btn.querySelector('img');if(!img)return;boxImg.src=img.currentSrc||img.src;boxImg.alt=img.alt||'';box.classList.add('open');box.setAttribute('aria-hidden','false')}));
    box.querySelector('button').addEventListener('click',closeImage);box.addEventListener('click',e=>{if(e.target===box)closeImage()});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&box.classList.contains('open'))closeImage()});
  }
  document.querySelectorAll('.lore-image img').forEach(img=>{const classify=()=>{const figure=img.closest('.lore-image');if(!figure||figure.classList.contains('lore-entity-portrait')||[...figure.classList].some(x=>x.startsWith('lore-image-layout-')))return;const ratio=img.naturalWidth/Math.max(1,img.naturalHeight);figure.classList.toggle('lore-image-smart-portrait',ratio<.78);figure.classList.toggle('lore-image-smart-square',ratio>=.78&&ratio<1.18);figure.classList.toggle('lore-image-smart-landscape',ratio>=1.18&&ratio<=1.8);figure.classList.toggle('lore-image-smart-panorama',ratio>1.8)};if(img.complete)classify();else img.addEventListener('load',classify,{once:true})});

  // Loreforge-only parallax is deliberately restrained so reading never becomes
  // nauseating. Reduced-motion users get static artwork automatically.
  const parallax=[...document.querySelectorAll('.lore-image-parallax')];
  if(parallax.length&&!matchMedia('(prefers-reduced-motion: reduce)').matches){let raf=0;const update=()=>{raf=0;parallax.forEach(el=>{const r=el.getBoundingClientRect(),offset=Math.max(-18,Math.min(18,(innerHeight/2-(r.top+r.height/2))*.035));el.style.setProperty('--lf-parallax',offset+'px')})};addEventListener('scroll',()=>{if(!raf)raf=requestAnimationFrame(update)},{passive:true});update()}

  const sceneParallax=[...document.querySelectorAll('.lore-scene-parallax')];
  if(sceneParallax.length&&!matchMedia('(prefers-reduced-motion: reduce)').matches){let sceneRaf=0;const updateScenes=()=>{sceneRaf=0;sceneParallax.forEach(el=>{const r=el.getBoundingClientRect(),offset=Math.max(-30,Math.min(30,(innerHeight/2-(r.top+r.height/2))*.045));el.style.setProperty('--scene-parallax',offset+'px')})};addEventListener('scroll',()=>{if(!sceneRaf)sceneRaf=requestAnimationFrame(updateScenes)},{passive:true});updateScenes()}

  // Long entries receive a compact local outline generated from their LaTeX
  // section/subsection structure. Highlight the section currently being read.
  const outline=document.querySelector('[data-article-outline]');
  if(outline){const links=[...outline.querySelectorAll('[data-outline-link]')],heads=links.map(a=>document.getElementById(a.dataset.outlineLink)).filter(Boolean);if(heads.length){const activate=id=>links.forEach(a=>a.classList.toggle('active',a.dataset.outlineLink===id));const obs=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top);if(visible[0])activate(visible[0].target.id)},{rootMargin:'-18% 0px -68% 0px',threshold:[0,1]});heads.forEach(h=>obs.observe(h));links.forEach(a=>a.addEventListener('click',()=>activate(a.dataset.outlineLink)))}}

  // Private browser-side player journal: bookmarks + recently viewed pages.
  const pageShell=document.querySelector('[data-page-slug]');
  const bookmarkKey='loreforge.player.bookmarks',recentKey='loreforge.player.recent';
  const readStore=(key)=>{try{return JSON.parse(localStorage.getItem(key)||'[]')}catch(_){return[]}};
  const writeStore=(key,value)=>localStorage.setItem(key,JSON.stringify(value));
  if(pageShell){
    const item={slug:pageShell.dataset.pageSlug,title:pageShell.dataset.pageTitle,chapter:pageShell.dataset.pageChapter,image:pageShell.dataset.pageImage||'',href:'/wiki/'+pageShell.dataset.pageSlug,seen:Date.now()};
    let recent=readStore(recentKey).filter(x=>x.slug!==item.slug);recent.unshift(item);writeStore(recentKey,recent.slice(0,16));
    const bookmarkBtn=document.querySelector('[data-bookmark-page]');
    const renderBookmark=()=>{const saved=readStore(bookmarkKey).some(x=>x.slug===item.slug);bookmarkBtn?.classList.toggle('active',saved);if(bookmarkBtn)bookmarkBtn.innerHTML=saved?'<span>★</span> Saved to journal':'<span>☆</span> Save to journal'};renderBookmark();
    bookmarkBtn?.addEventListener('click',()=>{let saved=readStore(bookmarkKey),has=saved.some(x=>x.slug===item.slug);saved=has?saved.filter(x=>x.slug!==item.slug):[{...item,seen:Date.now()},...saved];writeStore(bookmarkKey,saved.slice(0,30));renderBookmark()});
    document.querySelector('[data-copy-page-link]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(location.href);const b=document.querySelector('[data-copy-page-link]');const old=b.textContent;b.textContent='✓ Copied';setTimeout(()=>b.textContent=old,1200)}catch(_){}})
  }
  const trail=document.getElementById('personalTrail'),trailSection=document.getElementById('personalTrailSection');
  if(trail&&trailSection){const bookmarks=readStore(bookmarkKey).map(x=>({...x,bookmarked:true})),recent=readStore(recentKey),seen=new Set(),items=[];for(const x of [...bookmarks,...recent]){if(!x?.slug||seen.has(x.slug))continue;seen.add(x.slug);items.push(x);if(items.length>=8)break}if(items.length){trailSection.classList.remove('hidden');trail.innerHTML=items.map(x=>`<a class="trail-card ${x.image?'has-image':''}" href="${escapeHtml(x.href||('/wiki/'+x.slug))}" ${x.image?`style="--trail-image:url('${escapeHtml(x.image)}')"`:''}><small>${escapeHtml((x.bookmarked?'★ SAVED · ':'')+(x.chapter||'Setting'))}</small><strong>${escapeHtml(x.title||'Lore')}</strong><i>→</i></a>`).join('')}}

  function escapeHtml(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
})();
