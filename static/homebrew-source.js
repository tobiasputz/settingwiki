(()=>{
  const $=s=>document.querySelector(s);
  const toast=(msg,bad=false)=>{let n=$('#homebrewToast');if(!n){n=document.createElement('div');n.id='homebrewToast';n.className='v6-toast';document.body.appendChild(n)}n.textContent=msg;n.classList.toggle('bad',bad);n.classList.add('show');clearTimeout(n._t);n._t=setTimeout(()=>n.classList.remove('show'),3800)};
  const button=$('[data-homebrew-source-foundry]');if(!button)return;
  button.addEventListener('click',async()=>{button.disabled=true;try{const r=await fetch(`/api/homebrew/source/${encodeURIComponent(button.dataset.homebrewSourceFoundry)}/foundry`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const out=await r.json().catch(()=>({}));if(!r.ok)throw Error(out.detail||out.message||`Request failed (${r.status})`);toast(`Foundry import queued · ${out.rules||0} rule${out.rules===1?'':'s'} · command #${out.command?.id||'—'}`)}catch(e){toast(e.message,true)}finally{button.disabled=false}});
})();
