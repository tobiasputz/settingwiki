(()=>{
  const $=(s,p=document)=>p.querySelector(s), $$=(s,p=document)=>[...p.querySelectorAll(s)];
  document.querySelectorAll('[data-epoch]').forEach(el=>{const n=Number(el.dataset.epoch||0);if(n)el.textContent=new Date(n*1000).toLocaleString([], {dateStyle:'medium',timeStyle:'short'})});
  const send=async(url,method='POST',body)=>{const r=await fetch(url,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.detail||'Request failed');return j};
  const toast=(msg,bad=false)=>{const n=document.createElement('div');n.className=`v6-toast${bad?' bad':''}`;n.textContent=msg;document.body.appendChild(n);requestAnimationFrame(()=>n.classList.add('show'));setTimeout(()=>{n.classList.remove('show');setTimeout(()=>n.remove(),220)},2200)};
  const entityId=Number(location.pathname.match(/\/entity\/(\d+)/)?.[1]||0);

  $$('[data-share-fact]').forEach(b=>b.addEventListener('click',async()=>{b.disabled=true;try{const out=await send(`/api/v7/facts/${b.dataset.shareFact}/share-party`,'POST',{});toast(`Shared with the party (${out.count||0} members).`);b.textContent='✓ Shared'}catch(err){toast(err.message,true);b.disabled=false}}));
  $$('[data-observation-visibility]').forEach(b=>b.addEventListener('click',async()=>{b.disabled=true;try{await send(`/api/v7/observations/${b.dataset.observationVisibility}/visibility`,'POST',{visibility:b.dataset.visibility});toast(b.dataset.visibility==='party'?'Shared with the party.':'Kept private.');location.reload()}catch(err){toast(err.message,true);b.disabled=false}}));
  $$('[data-delete-observation]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Delete this deduction?'))return;try{await send(`/api/v7/observations/${b.dataset.deleteObservation}`,'DELETE');location.reload()}catch(err){toast(err.message,true)}}));
  $$('[data-review-observation]').forEach(b=>b.addEventListener('click',async()=>{try{await send(`/api/v7/observations/${b.dataset.reviewObservation}/review`,'POST',{status:b.dataset.status});toast(`Deduction ${b.dataset.status}.`);location.reload()}catch(err){toast(err.message,true)}}));

  const dialog=$('[data-observation-dialog]'),form=$('#v7ObservationForm');
  $('[data-open-observation]')?.addEventListener('click',()=>dialog?.showModal());
  $$('[data-observation-kind]').forEach(b=>b.addEventListener('click',()=>{const kind=b.dataset.observationKind;$$('[data-observation-kind]').forEach(x=>x.classList.toggle('active',x===b));if(form)form.elements.kind.value=kind;const range=$('[data-observation-range-fields]');if(range)range.hidden=kind!=='range'}));
  form?.elements.metric?.addEventListener('change',()=>{const box=$('[data-ac-evidence]');if(box)box.hidden=form.elements.metric.value!=='ac'});
  form?.addEventListener('submit',async ev=>{ev.preventDefault();if(!entityId)return;const fd=new FormData(form),kind=String(fd.get('kind')||'range');const payload={kind,metric:kind==='range'?String(fd.get('metric')||''):'',title:String(fd.get('title')||''),body:String(fd.get('body')||''),visibility:fd.get('share_party')?'party':'private'};if(kind==='range'){payload.lower_bound=fd.get('lower_bound');payload.upper_bound=fd.get('upper_bound');if(payload.metric==='ac'){payload.miss_total=fd.get('miss_total');payload.hit_total=fd.get('hit_total')}}try{await send(`/api/v7/entities/${entityId}/observations`,'POST',payload);toast('Field deduction saved.');dialog.close();location.reload()}catch(err){toast(err.message,true)}});
})();
