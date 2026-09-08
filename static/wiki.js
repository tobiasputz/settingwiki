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
  function escapeHtml(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
})();
