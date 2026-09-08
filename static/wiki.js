(()=>{
  const overlay=document.getElementById('searchOverlay'), input=document.getElementById('globalSearch'), results=document.getElementById('searchResults');
  const open=()=>{if(!overlay)return;overlay.classList.add('open');overlay.setAttribute('aria-hidden','false');setTimeout(()=>input?.focus(),40)};
  const close=()=>{overlay?.classList.remove('open');overlay?.setAttribute('aria-hidden','true')};
  document.querySelectorAll('[data-open-search]').forEach(b=>b.addEventListener('click',open));
  overlay?.addEventListener('click',e=>{if(e.target===overlay)close()});
  document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)){e.preventDefault();open()} if(e.key==='Escape')close()});
  let timer; input?.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(async()=>{const q=input.value.trim();if(!q){results.innerHTML='<div class="search-hint">Type a place, person, faction, item, or phrase.</div>';return} const data=await fetch('/api/public/search?q='+encodeURIComponent(q)).then(r=>r.json());results.innerHTML=data.length?data.map(x=>`<a class="search-result" href="/wiki/${x.slug}"><small>${escapeHtml(x.chapter||'Setting')}</small><strong>${escapeHtml(x.title)}</strong><p>${escapeHtml(x.excerpt||'')}</p></a>`).join(''):'<div class="search-hint">No matching lore found.</div>'},180)});
  const progress=document.getElementById('readingProgress'); if(progress){const update=()=>{const h=document.documentElement.scrollHeight-innerHeight;progress.style.width=(h?scrollY/h*100:0)+'%'};addEventListener('scroll',update,{passive:true});update()}
  document.querySelectorAll('time[data-epoch]').forEach(t=>{const d=new Date(Number(t.dataset.epoch)*1000);t.textContent=d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})});
  const io=new IntersectionObserver(entries=>entries.forEach(x=>x.isIntersecting&&x.target.classList.add('visible')),{threshold:.08});document.querySelectorAll('.reveal').forEach(x=>io.observe(x));
  // Any rendered LaTeX image can be inspected at full resolution.  This is
  // especially useful for maps, family trees, handouts, and NPC artwork.
  const zoomButtons=[...document.querySelectorAll('.lore-image-zoom')];
  if(zoomButtons.length){
    const box=document.createElement('div');box.className='lore-lightbox';box.setAttribute('aria-hidden','true');box.innerHTML='<button type="button" aria-label="Close image">×</button><img alt="">';document.body.appendChild(box);
    const boxImg=box.querySelector('img');
    const closeImage=()=>{box.classList.remove('open');box.setAttribute('aria-hidden','true');boxImg.removeAttribute('src')};
    zoomButtons.forEach(btn=>btn.addEventListener('click',()=>{const img=btn.querySelector('img');if(!img)return;boxImg.src=img.currentSrc||img.src;boxImg.alt=img.alt||'';box.classList.add('open');box.setAttribute('aria-hidden','false')}));
    box.querySelector('button').addEventListener('click',closeImage);box.addEventListener('click',e=>{if(e.target===box)closeImage()});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&box.classList.contains('open'))closeImage()});
  }
  // Infer a web-friendly presentation from the actual image aspect ratio.
  // LaTeX width rules are page-oriented; the wiki can make portraits compact
  // and panoramas expansive without requiring campaign-source changes.
  document.querySelectorAll('.lore-image img').forEach(img=>{
    const classify=()=>{const figure=img.closest('.lore-image');if(!figure||figure.classList.contains('lore-entity-portrait'))return;const ratio=img.naturalWidth/Math.max(1,img.naturalHeight);figure.classList.toggle('lore-image-smart-portrait',ratio<.78);figure.classList.toggle('lore-image-smart-square',ratio>=.78&&ratio<1.18);figure.classList.toggle('lore-image-smart-landscape',ratio>=1.18&&ratio<=1.8);figure.classList.toggle('lore-image-smart-panorama',ratio>1.8)};
    if(img.complete)classify();else img.addEventListener('load',classify,{once:true});
  });
  function escapeHtml(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
})();
