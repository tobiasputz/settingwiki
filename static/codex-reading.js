/* Seeker Codex reading preferences and optional resume positions.
   Purely local preferences: no campaign text or player data is uploaded. */
(() => {
  'use strict';
  const shell=document.querySelector('.reading-shell[data-page-slug]');
  const toolbar=document.getElementById('codexReadingTools');
  if(!shell||!toolbar)return;
  const article=shell.querySelector('[data-lore-article]');
  const key='seeker.reader.preferences';
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  let prefs={focus:false,size:1};
  try{prefs={...prefs,...JSON.parse(localStorage.getItem(key)||'{}')}}catch(_){}
  prefs.size=clamp(Number(prefs.size)||1,0.9,1.3);
  function apply(){
    shell.classList.toggle('reader-focus',!!prefs.focus);
    shell.style.setProperty('--reader-scale',String(prefs.size));
    const focus=toolbar.querySelector('[data-reader-focus]');if(focus){focus.setAttribute('aria-pressed',String(!!prefs.focus));focus.textContent=prefs.focus?'Exit focus':'Focus reading';}
    toolbar.querySelector('[data-reader-size-display]').textContent=Math.round(prefs.size*100)+'%';
    try{localStorage.setItem(key,JSON.stringify(prefs))}catch(_){}
  }
  toolbar.querySelector('[data-reader-focus]')?.addEventListener('click',()=>{prefs.focus=!prefs.focus;apply()});
  toolbar.querySelector('[data-reader-smaller]')?.addEventListener('click',()=>{prefs.size=clamp(Math.round((prefs.size-.1)*10)/10,.9,1.3);apply()});
  toolbar.querySelector('[data-reader-larger]')?.addEventListener('click',()=>{prefs.size=clamp(Math.round((prefs.size+.1)*10)/10,.9,1.3);apply()});
  apply();
  if(!article)return;
  const progressKey='seeker.reader.last.'+String(shell.dataset.pageSlug||'');
  let previous=null;
  try{previous=JSON.parse(localStorage.getItem(progressKey)||'null')}catch(_){}
  const resume=toolbar.querySelector('[data-reader-resume]');
  if(resume&&previous&&Date.now()-previous.at<30*864e5&&previous.ratio>.1&&previous.ratio<.95&&!location.hash){
    resume.hidden=false;
    resume.addEventListener('click',()=>{const h=article.getBoundingClientRect().height,top=article.getBoundingClientRect().top+scrollY;scrollTo({top:top+h*previous.ratio,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});resume.hidden=true;});
  }
  let pending=false;
  function storePosition(){
    if(pending)return;pending=true;
    requestAnimationFrame(()=>{
      pending=false;
      const r=article.getBoundingClientRect(),h=Math.max(1,r.height),ratio=clamp((scrollY-r.top-scrollY)/h,0,1);
      try{localStorage.setItem(progressKey,JSON.stringify({ratio,at:Date.now()}))}catch(_){}
    });
  }
  addEventListener('scroll',storePosition,{passive:true});
})();
