(()=>{
  const overlay=document.getElementById('searchOverlay'), input=document.getElementById('globalSearch'), results=document.getElementById('searchResults');
  let searchItems=[],searchIndex=-1;
  const searchLanding=()=>{
    if(!results)return;let recent=[];try{recent=JSON.parse(localStorage.getItem('loreforge.player.recent')||'[]').slice(0,5)}catch{}
    results.innerHTML=`<div class="palette-home"><div class="palette-home-section"><small class="palette-home-label">Quick jumps</small><div class="palette-quick-grid"><a href="/session">✦ Session</a><a href="/schedule">◷ Planner</a><a href="/campaign">◇ Chronicle</a><a href="/characters">♟ Characters</a><a href="/mysteries">? Mysteries</a></div></div>${recent.length?`<div class="palette-home-section"><small class="palette-home-label">Recently viewed</small><div class="palette-recent-list">${recent.map(x=>`<a href="${escapeHtml(x.href||('/wiki/'+x.slug))}"><strong>${escapeHtml(x.title||'Lore')}</strong><small>${escapeHtml(x.chapter||'Setting')}</small></a>`).join('')}</div></div>`:''}</div>`;
  };
  const open=()=>{if(!overlay)return;overlay.classList.add('open');overlay.setAttribute('aria-hidden','false');if(!input?.value.trim())searchLanding();setTimeout(()=>input?.focus(),40)};
  const close=()=>{overlay?.classList.remove('open');overlay?.setAttribute('aria-hidden','true');searchIndex=-1};
  document.querySelectorAll('[data-open-search]').forEach(b=>b.addEventListener('click',open));
  overlay?.addEventListener('click',e=>{if(e.target===overlay)close()});
  document.addEventListener('click',e=>{const menus=[...document.querySelectorAll('[data-nav-menu][open]')];menus.forEach(m=>{if(!m.contains(e.target))m.removeAttribute('open')});const opened=e.target.closest('[data-nav-menu]');if(opened)menus.forEach(m=>{if(m!==opened)m.removeAttribute('open')})});
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
  let timer,searchAbort=null; input?.addEventListener('input',()=>{clearTimeout(timer);searchAbort?.abort();timer=setTimeout(async()=>{const q=input.value.trim();searchIndex=-1;if(!q){searchLanding();return}searchAbort=new AbortController();try{const data=await fetch('/api/public/search?q='+encodeURIComponent(q),{signal:searchAbort.signal,cache:'no-store'}).then(r=>r.json());searchItems=data;results.innerHTML=data.length?data.map(x=>`<a class="search-result" href="${escapeHtml(x.href||('/wiki/'+x.slug))}"><small>${escapeHtml(x.chapter||'Setting')}<span class="search-type">${escapeHtml(x.type||'lore')}</span></small><strong>${escapeHtml(x.title)}</strong><p>${escapeHtml(x.excerpt||'')}</p></a>`).join(''):'<div class="search-hint">No matching lore found.</div>'}catch(err){if(err?.name!=='AbortError')results.innerHTML='<div class="search-hint">Search is temporarily unavailable.</div>'}},240)});

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

  // Seeker-only parallax is deliberately restrained so reading never becomes
  // nauseating. Reduced-motion users get static artwork automatically.
  const parallax=[...document.querySelectorAll('.lore-image-parallax')];
  if(parallax.length&&!matchMedia('(prefers-reduced-motion: reduce)').matches){let raf=0;const update=()=>{raf=0;parallax.forEach(el=>{const r=el.getBoundingClientRect(),offset=Math.max(-18,Math.min(18,(innerHeight/2-(r.top+r.height/2))*.035));el.style.setProperty('--lf-parallax',offset+'px')})};addEventListener('scroll',()=>{if(!raf)raf=requestAnimationFrame(update)},{passive:true});update()}

  const sceneParallax=[...document.querySelectorAll('.lore-scene-parallax')];
  if(sceneParallax.length&&!matchMedia('(prefers-reduced-motion: reduce)').matches){let sceneRaf=0;const updateScenes=()=>{sceneRaf=0;sceneParallax.forEach(el=>{const r=el.getBoundingClientRect(),offset=Math.max(-30,Math.min(30,(innerHeight/2-(r.top+r.height/2))*.045));el.style.setProperty('--scene-parallax',offset+'px')})};addEventListener('scroll',()=>{if(!sceneRaf)sceneRaf=requestAnimationFrame(updateScenes)},{passive:true});updateScenes()}

  // GM source bridge: when the admin reads the player-facing Codex, a persistent
  // edit control opens the exact LaTeX file/line in Campaign Studio. On long
  // entity pages the target follows the currently active section.
  const gmEditLinks=[...document.querySelectorAll('[data-gm-edit-source]')];
  const gmEditHref=(file,line)=>{const u=new URL('/admin',location.origin),activeHash=document.querySelector('[data-outline-link].active')?.getAttribute('href')||location.hash||'';u.searchParams.set('file',file||'');u.searchParams.set('line',String(Math.max(1,Number(line)||1)));u.searchParams.set('from',location.pathname+location.search+activeHash);return u.pathname+u.search};
  const updateGmEditTarget=(file,line)=>{if(!file)return;gmEditLinks.forEach(a=>{a.href=gmEditHref(file,line);a.dataset.sourceFile=file;a.dataset.sourceLine=String(line||1);const small=a.querySelector('small');if(small)small.textContent=`${file} · line ${line||1}`})};
  if(gmEditLinks.length){const first=gmEditLinks[0];updateGmEditTarget(first.dataset.sourceFile,first.dataset.sourceLine)}

  // Long entries receive a compact local outline generated from their LaTeX
  // section/subsection structure. Highlight the section currently being read.
  const outline=document.querySelector('[data-article-outline]');
  if(outline){const links=[...outline.querySelectorAll('[data-outline-link]')],heads=links.map(a=>document.getElementById(a.dataset.outlineLink)).filter(Boolean);if(heads.length){const activate=id=>{links.forEach(a=>a.classList.toggle('active',a.dataset.outlineLink===id));const active=links.find(a=>a.dataset.outlineLink===id);if(active?.dataset.sourceFile)updateGmEditTarget(active.dataset.sourceFile,active.dataset.sourceLine)};const obs=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top);if(visible[0])activate(visible[0].target.id)},{rootMargin:'-18% 0px -68% 0px',threshold:[0,1]});heads.forEach(h=>obs.observe(h));links.forEach(a=>a.addEventListener('click',()=>activate(a.dataset.outlineLink)))}}

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

  // A setting can host several table campaigns. Switching table scope is a
  // server-side session preference so every route/API immediately sees the
  // same characters, sessions, notes and spoiler state.
  document.querySelectorAll('[data-campaign-select]').forEach(select=>select.addEventListener('change',async()=>{
    if(select.value==='__all__'){location.href='/tables';return}
    const previous=document.body.dataset.campaignId||'';select.disabled=true;
    try{const r=await fetch('/api/campaign/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({campaign_id:Number(select.value)})});if(!r.ok)throw new Error((await r.json().catch(()=>({}))).detail||'Could not switch campaign.');location.href=location.pathname==='/tables'?'/':location.href}catch(err){select.value=previous;select.disabled=false;alert(err.message||'Could not switch campaign.')}
  }));
  document.querySelectorAll('[data-table-enter]').forEach(btn=>btn.addEventListener('click',async e=>{e.preventDefault();btn.disabled=true;try{const r=await fetch('/api/campaign/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({campaign_id:Number(btn.dataset.tableEnter)})});if(!r.ok)throw Error((await r.json().catch(()=>({}))).detail||'Could not enter table.');location.href=btn.dataset.tableHref||'/'}catch(err){btn.disabled=false;alert(err.message)}}));

  // Seeker 2 — installable phone/tablet experience.
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
  // Browser-local campaign data must not bleed between two personal invitation
  // identities used on the same device. A changed access key clears private
  // offline content and requires the new player to opt in again.
  const accessKey=document.body.dataset.playerAccessKey||'',storedAccessKey=localStorage.getItem('loreforge.playerAccessKey')||'';
  if(accessKey&&storedAccessKey&&accessKey!==storedAccessKey){localStorage.setItem('loreforge.offline.enabled','0');if('serviceWorker' in navigator)navigator.serviceWorker.ready.then(r=>r.active?.postMessage('CLEAR_PRIVATE')).catch(()=>{})}
  if(accessKey)localStorage.setItem('loreforge.playerAccessKey',accessKey);
  const moreBtn=document.querySelector('[data-mobile-more]'),moreSheet=document.getElementById('mobileMoreSheet');
  moreBtn?.addEventListener('click',()=>{const open=!moreSheet.classList.contains('open');moreSheet.classList.toggle('open',open);moreSheet.setAttribute('aria-hidden',open?'false':'true')});
  document.addEventListener('click',e=>{if(moreSheet?.classList.contains('open')&&!moreSheet.contains(e.target)&&!moreBtn?.contains(e.target)){moreSheet.classList.remove('open');moreSheet.setAttribute('aria-hidden','true')}});
  const installBanner=document.getElementById('installBanner'),installBtn=document.getElementById('installAppBtn'),installHint=document.getElementById('installHint');let installPrompt=null;
  const dismissed=localStorage.getItem('loreforge.install.dismissed')==='1',standalone=matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
  const isiOS=/iphone|ipad|ipod/i.test(navigator.userAgent);
  if(!dismissed&&!standalone){if(isiOS){installBanner?.classList.remove('hidden');if(installHint)installHint.textContent='On iPhone/iPad: Share → Add to Home Screen.';if(installBtn)installBtn.textContent='How';installBtn?.addEventListener('click',()=>alert('Safari: tap the Share button, then “Add to Home Screen”. Seeker will open like an app.'))}else{window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;installBanner?.classList.remove('hidden')});installBtn?.addEventListener('click',async()=>{if(!installPrompt)return;installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;installBanner?.classList.add('hidden')})}}
  document.querySelector('[data-dismiss-install]')?.addEventListener('click',()=>{installBanner?.classList.add('hidden');localStorage.setItem('loreforge.install.dismissed','1')});

  // Explicit private offline cache. Invitation-protected campaign pages are only
  // retained after the player opts in; turning this off asks the service worker
  // to purge all cached campaign HTML immediately.
  const offlineBtn=document.querySelector('[data-offline-toggle]');
  const offlineKey='loreforge.offline.enabled';
  const offlineState=()=>localStorage.getItem(offlineKey)==='1';
  const renderOffline=()=>{if(offlineBtn)offlineBtn.textContent=offlineState()?'⇩ Offline cache: on':'⇩ Offline cache: off'};renderOffline();
  offlineBtn?.addEventListener('click',async()=>{const enabled=!offlineState();localStorage.setItem(offlineKey,enabled?'1':'0');renderOffline();try{const reg=await navigator.serviceWorker.ready;reg.active?.postMessage(enabled?'OFFLINE_ON':'OFFLINE_OFF')}catch(_){}});
  if('serviceWorker' in navigator&&offlineState())navigator.serviceWorker.ready.then(reg=>reg.active?.postMessage('OFFLINE_ON')).catch(()=>{});
  document.querySelectorAll('[data-player-logout]').forEach(btn=>btn.addEventListener('click',async()=>{
    if(!confirm('Sign out of this campaign on this device?'))return;
    localStorage.setItem(offlineKey,'0');localStorage.removeItem('loreforge.playerAccessKey');
    try{const reg=await navigator.serviceWorker.ready;reg.active?.postMessage('CLEAR_PRIVATE')}catch(_){}
    try{await fetch('/api/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})}catch(_){}
    location.href='/';
  }));

  // Command palette augments search with fast navigation and GM-only actions.
  const adminMode=document.body.dataset.adminView==='true';
  const baseInputHandler=input?.oninput;
  const commandRows=q=>{const low=q.toLowerCase().trim(),rows=[];const add=(title,chapter,href,excerpt='')=>rows.push({title,chapter,href,excerpt,type:'command'});if('session'.includes(low)||low.startsWith('session'))add(adminMode?'Open Session Console':'Open player session','Command',adminMode?'/gm/session':'/session','Run or follow the current session.');if('tables'.includes(low)||'campaigns'.includes(low))add('Open All Tables','Command','/tables','See every campaign you belong to.');if('schedule'.includes(low)||'planner'.includes(low)||'availability'.includes(low))add('Open Session Planner','Command','/schedule','Mark availability or find the next shared date.');if('timeline'.includes(low))add('Open timeline','Command','/timeline','Browse campaign chronology.');if('mysteries'.includes(low)||low==='board')add('Open mystery board','Command','/mysteries','Clues, theories, and unresolved threads.');if(adminMode&&low.startsWith('edit ')){const name=q.slice(5).trim();add('Edit '+name,'GM command','/admin?search='+encodeURIComponent(name),'Jump into Seeker Studio.')}if(adminMode&&('worldcraft'.includes(low)||'campaign control'.includes(low)||low==='control'))add('Open Worldcraft','GM command','/admin/campaign','Canon, reveals, timeline, handouts, lore health, and snapshots.');return rows};
  if(input){input.addEventListener('input',()=>{const q=input.value.trim();if(!q)return;setTimeout(()=>{const commands=commandRows(q);if(!commands.length)return;const existing=results.querySelectorAll('.search-result').length;const html=commands.map(x=>`<a class="search-result command-result" href="${escapeHtml(x.href)}"><small>${escapeHtml(x.chapter)}<span class="search-type">command</span></small><strong>${escapeHtml(x.title)}</strong><p>${escapeHtml(x.excerpt)}</p></a>`).join('');results.insertAdjacentHTML('afterbegin',html)},190)})}

  // Rich hover previews for linked Codex names. Disabled on touch-first devices.
  const hoverCard=document.getElementById('loreHoverCard');let hoverTimer=0,hoverAbort=null;const hoverCache=new Map();
  if(hoverCard&&matchMedia('(hover:hover) and (pointer:fine)').matches){document.body.addEventListener('mouseover',e=>{const a=e.target.closest('a[href^="/wiki/"]');if(!a)return;clearTimeout(hoverTimer);hoverTimer=setTimeout(async()=>{const slug=a.getAttribute('href').split('/wiki/')[1]?.split(/[?#]/)[0];if(!slug)return;hoverAbort?.abort();hoverAbort=new AbortController();try{let d=hoverCache.get(slug);if(!d){d=await fetch('/api/public/page-card/'+encodeURIComponent(slug),{signal:hoverAbort.signal,cache:'no-store'}).then(r=>r.json());hoverCache.set(slug,d);if(hoverCache.size>32)hoverCache.delete(hoverCache.keys().next().value)}hoverCard.innerHTML=`${d.image?`<div class="hover-card-art" style="background-image:url('${escapeHtml(d.image)}')"></div>`:''}<small>${escapeHtml(d.chapter||'SETTING')}</small><strong>${escapeHtml(d.title)}</strong><p>${escapeHtml(d.excerpt||'')}</p>${(d.relationships||[]).length?`<div class="hover-relations">${d.relationships.slice(0,3).map(r=>`<span>${escapeHtml(r.label||r.relation)}</span>`).join('')}</div>`:''}`;const r=a.getBoundingClientRect();hoverCard.style.left=Math.min(innerWidth-330,Math.max(12,r.left))+'px';hoverCard.style.top=Math.min(innerHeight-240,Math.max(70,r.bottom+8))+'px';hoverCard.classList.add('open');hoverCard.setAttribute('aria-hidden','false')}catch(_){}} ,320)});document.body.addEventListener('mouseout',e=>{if(e.target.closest('a[href^="/wiki/"]')){clearTimeout(hoverTimer);hoverTimer=setTimeout(()=>{hoverCard.classList.remove('open');hoverCard.setAttribute('aria-hidden','true')},120)}})}

  // Selection-based player annotations and GM margin notes.
  if(pageShell){const noteBubble=document.createElement('button');noteBubble.type='button';noteBubble.className='selection-note-bubble';noteBubble.textContent=adminMode?'＋ GM note':'＋ Note';document.body.appendChild(noteBubble);let selectedText='',selectedAnchor='';const hideBubble=()=>noteBubble.classList.remove('open');document.addEventListener('selectionchange',()=>{const sel=getSelection();if(!sel||sel.isCollapsed||!document.querySelector('[data-lore-article]')?.contains(sel.anchorNode)){hideBubble();return}selectedText=sel.toString().trim().slice(0,500);if(!selectedText){hideBubble();return}const range=sel.getRangeAt(0),rect=range.getBoundingClientRect();const heading=sel.anchorNode?.parentElement?.closest('section,h2,h3,h4')?.id||location.hash.replace('#','')||'';selectedAnchor=heading;noteBubble.style.left=Math.max(8,Math.min(innerWidth-110,rect.left+rect.width/2-45))+'px';noteBubble.style.top=(scrollY+rect.top-42)+'px';noteBubble.classList.add('open')});noteBubble.onclick=()=>{hideBubble();const note=prompt(adminMode?'Private GM margin note:':'Add a note to this passage:');if(!note)return;const visibility=adminMode?'gm':(confirm('Share this note with the whole party?\nOK = party note · Cancel = private note')?'party':'private');fetch('/api/public/annotations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page_slug:pageShell.dataset.pageSlug,anchor:selectedAnchor,quote:selectedText,note,visibility})}).then(r=>r.json()).then(()=>{const tray=document.querySelector('[data-annotation-tray]');if(tray)loadNotes(tray);}).catch(()=>{})};async function loadNotes(tray){try{const notes=await fetch('/api/public/annotations/'+encodeURIComponent(pageShell.dataset.pageSlug)).then(r=>r.json());tray.innerHTML=notes.length?notes.map(n=>`<article class="margin-note ${escapeHtml(n.visibility)}"><div class="margin-note-head"><small>${escapeHtml(n.visibility.toUpperCase())}${n.author_label?' · '+escapeHtml(n.author_label):''}</small>${n.can_delete?`<button type="button" data-delete-annotation="${n.id}" title="Delete note">×</button>`:''}</div>${n.quote?`<blockquote>${escapeHtml(n.quote)}</blockquote>`:''}<p>${escapeHtml(n.note)}</p></article>`).join(''):'<div class="empty-mini">No notes on this entry yet.</div>';tray.querySelectorAll('[data-delete-annotation]').forEach(b=>b.onclick=async()=>{if(!confirm('Delete this Codex note?'))return;b.disabled=true;const r=await fetch('/api/public/annotations/'+b.dataset.deleteAnnotation,{method:'DELETE'});if(r.ok)loadNotes(tray);else{b.disabled=false;alert((await r.json().catch(()=>({}))).detail||'Could not delete this note.')}})}catch(_){}}const tray=document.querySelector('[data-annotation-tray]');if(tray)loadNotes(tray);
    fetch('/api/public/activity',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event_type:'view',target_key:pageShell.dataset.pageSlug})}).catch(()=>{});
    // Sync bookmarks to the invitation identity while retaining local fallback.
    const syncBookmarkBtn=document.querySelector('[data-bookmark-page]');
    syncBookmarkBtn?.addEventListener('click',()=>setTimeout(()=>{const slug=pageShell.dataset.pageSlug;const enabled=readStore(bookmarkKey).some(x=>x.slug===slug);fetch('/api/public/bookmark/'+encodeURIComponent(slug),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})}).catch(()=>{})},20));
  }

  // Player Session Mode is live without websockets: invited devices poll a tiny
  // timestamp endpoint and refresh only when the GM changes the live session, a
  // reveal, handout, or discovery feed. This keeps Railway deployment simple.
  const sessionScreen=document.querySelector('[data-session-pulse]');
  if(sessionScreen){let pulse=null,busy=false;const poll=async()=>{if(busy||document.hidden)return;busy=true;try{const next=await fetch('/api/public/session-pulse',{cache:'no-store'}).then(r=>r.json());if(pulse&&(next.session_id!==pulse.session_id||next.session_updated>pulse.session_updated||next.latest_update>pulse.latest_update||next.latest_reveal>pulse.latest_reveal||next.latest_handout>pulse.latest_handout)){location.reload();return}pulse=next}catch(_){ }finally{busy=false}};poll();setInterval(poll,5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()})}

  // Share/QR helper for phones at the physical table.
  document.querySelectorAll('[data-share-qr]').forEach(btn=>btn.addEventListener('click',()=>{const path=btn.dataset.shareQr||location.pathname+location.search;const box=document.createElement('div');box.className='qr-share-modal';box.innerHTML=`<button type="button">×</button><small>SCAN AT THE TABLE</small><strong>${escapeHtml(document.title.split('·')[0].trim())}</strong><img src="/share/qr?path=${encodeURIComponent(path)}" alt="QR code"><p>Scanning opens this player-visible page. The player still needs a valid Seeker invitation session.</p>`;document.body.appendChild(box);box.querySelector('button').onclick=()=>box.remove()}));

  // Living Campaign notifications and GM “show this to players” pushes.
  const notificationDrawer=document.getElementById('notificationDrawer'),notificationFeed=document.getElementById('notificationFeed'),notificationCount=document.getElementById('notificationCount');let lastNotificationPoll=0,notificationRows=[];
  const notificationHref=n=>n.target_type==='page'||n.target_type==='lore'?('/wiki/'+n.target_key):n.target_type==='character'?('/characters/'+n.target_key):n.target_type==='thread'?('/campaign#threads'):n.target_type==='map'?('/atlas/'+n.target_key):n.target_type==='session'?'/session':n.target_type==='handout'?'/handouts':'';
  const renderNotifications=()=>{if(!notificationFeed)return;const unread=notificationRows.filter(x=>!x.read);if(notificationCount){notificationCount.textContent=unread.length?String(Math.min(99,unread.length)):'';notificationCount.classList.toggle('show',!!unread.length)}notificationFeed.innerHTML=notificationRows.length?notificationRows.map(n=>`<article class="notification-item kind-${escapeHtml(n.kind)} ${n.read?'read':''}" data-notification-row="${n.id}"><small>${escapeHtml((n.kind||'notice').toUpperCase())}</small><strong>${escapeHtml(n.title)}</strong><p>${escapeHtml(n.body||'')}</p><div>${notificationHref(n)?`<a href="${escapeHtml(notificationHref(n))}" data-notification-open="${n.id}">Open →</a>`:''}<button data-notification-read="${n.id}" ${n.read?'disabled':''}>${n.read?'Read':'Mark read'}</button><button class="notification-delete" data-notification-delete="${n.id}" title="Remove notification">Delete</button></div></article>`).join(''):'<div class="search-hint">No campaign notifications yet.</div>';notificationFeed.querySelectorAll('[data-notification-read]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const r=await fetch('/api/public/notifications/'+b.dataset.notificationRead+'/read',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',cache:'no-store'});if(!r.ok)throw Error();const n=notificationRows.find(x=>String(x.id)===b.dataset.notificationRead);if(n)n.read=true;renderNotifications()}catch(_){b.disabled=false}});notificationFeed.querySelectorAll('[data-notification-delete]').forEach(b=>b.onclick=async()=>{if(!confirm('Remove this notification?'))return;b.disabled=true;try{const r=await fetch('/api/public/notifications/'+b.dataset.notificationDelete,{method:'DELETE',cache:'no-store'});if(!r.ok)throw Error();notificationRows=notificationRows.filter(x=>String(x.id)!==b.dataset.notificationDelete);renderNotifications()}catch(_){b.disabled=false}});notificationFeed.querySelectorAll('[data-notification-open]').forEach(a=>a.addEventListener('click',()=>{const n=notificationRows.find(x=>String(x.id)===a.dataset.notificationOpen);if(n&&!n.read){n.read=true;fetch('/api/public/notifications/'+a.dataset.notificationOpen+'/read',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{})}}))};
  const pollNotifications=async()=>{if(document.hidden)return;try{const rows=await fetch('/api/public/notifications?since='+encodeURIComponent(lastNotificationPoll),{cache:'no-store'}).then(r=>r.ok?r.json():[]);if(rows.length){lastNotificationPoll=Math.max(lastNotificationPoll,...rows.map(x=>Number(x.created_at)||0));const known=new Set(notificationRows.map(x=>x.id));const fresh=rows.filter(x=>!known.has(x.id));notificationRows=[...fresh,...notificationRows].slice(0,60);renderNotifications();const spotlight=fresh.find(x=>x.kind==='spotlight');if(spotlight&&!document.hidden){const box=document.createElement('div');box.className='live-spotlight-toast';const href=notificationHref(spotlight);box.innerHTML=`<small>GM SPOTLIGHT</small><strong>${escapeHtml(spotlight.title)}</strong><p>${escapeHtml(spotlight.body||'')}</p>${href?`<a href="${escapeHtml(href)}">View now →</a>`:''}<button type="button">×</button>`;document.body.appendChild(box);box.querySelector('button').onclick=()=>box.remove();setTimeout(()=>box.remove(),12000)}}}catch(_){}};
  const loadNotificationPrefs=async()=>{const inputs=[...document.querySelectorAll('[data-notification-pref]')];if(!inputs.length)return;try{const prefs=await fetch('/api/v5/notification-prefs',{cache:'no-store'}).then(r=>r.ok?r.json():{});inputs.forEach(i=>i.checked=prefs[i.dataset.notificationPref]!==false)}catch(_){}};document.querySelectorAll('[data-notification-pref]').forEach(i=>i.addEventListener('change',async()=>{i.disabled=true;try{await fetch('/api/v5/notification-prefs/'+encodeURIComponent(i.dataset.notificationPref),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:i.checked})})}finally{i.disabled=false}}));document.querySelector('[data-notification-read-all]')?.addEventListener('click',async e=>{e.currentTarget.disabled=true;try{await fetch('/api/v5/notifications/read-all',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});notificationRows.forEach(n=>n.read=true);renderNotifications()}finally{e.currentTarget.disabled=false}});document.querySelector('[data-open-notifications]')?.addEventListener('click',()=>{notificationDrawer?.classList.add('open');notificationDrawer?.setAttribute('aria-hidden','false');pollNotifications();loadNotificationPrefs()});document.querySelector('[data-close-notifications]')?.addEventListener('click',()=>{notificationDrawer?.classList.remove('open');notificationDrawer?.setAttribute('aria-hidden','true')});
  pollNotifications();setInterval(pollNotifications,12000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollNotifications()});

  // Ambient audio is opt-in per entry and never autoplays.
  const ambient=document.querySelector('[data-ambient-audio]');if(ambient){const audio=new Audio(ambient.dataset.ambientAudio);audio.loop=true;audio.preload='none';ambient.addEventListener('click',async()=>{if(audio.paused){try{await audio.play();ambient.classList.add('playing');ambient.textContent='◼ Stop ambience'}catch(_){}}else{audio.pause();ambient.classList.remove('playing');ambient.textContent='♪ Ambience'}})}

  function escapeHtml(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}

  // V5: campaign-aware lore follows and private investigation pins.
  if(pageShell){
    const followBtn=document.querySelector('[data-follow-page]');
    if(followBtn){
      let followed=false;
      const sync=()=>{followBtn.classList.toggle('active',followed);followBtn.innerHTML=`<span>${followed?'★':'☆'}</span> ${followed?'Following':'Follow'}`};
      fetch('/api/v5/follows',{cache:'no-store'}).then(r=>r.ok?r.json():[]).then(rows=>{followed=rows.some(x=>x.target_type==='page'&&x.target_key===pageShell.dataset.pageSlug);sync()}).catch(()=>{});
      followBtn.addEventListener('click',async()=>{followBtn.disabled=true;try{const r=await fetch('/api/v5/follows',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_type:'page',target_key:pageShell.dataset.pageSlug,label:pageShell.dataset.pageTitle,enabled:!followed})});if(!r.ok)throw Error();followed=!followed;sync()}catch(_){alert('Could not update this follow.')}finally{followBtn.disabled=false}});
    }
    document.querySelector('[data-pin-investigation]')?.addEventListener('click',async e=>{const b=e.currentTarget;b.disabled=true;try{const r=await fetch('/api/v5/investigation/nodes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({node_type:'page',target_key:pageShell.dataset.pageSlug,title:pageShell.dataset.pageTitle,note:'',x:.5,y:.5})});if(!r.ok)throw Error();b.textContent='✓ Pinned to board';setTimeout(()=>b.textContent='⌘ Pin to board',2200)}catch(_){alert('Could not pin this lore entry.')}finally{b.disabled=false}});
  }
})();
