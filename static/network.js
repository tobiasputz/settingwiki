(()=>{
  const data=JSON.parse(document.getElementById('networkData')?.textContent||'{"nodes":[],"edges":[]}');
  const svg=document.getElementById('loreNetwork'), viewport=document.getElementById('networkViewport');
  const edgesLayer=document.getElementById('networkEdges'), nodesLayer=document.getElementById('networkNodes');
  const stage=document.getElementById('networkStage'), detail=document.getElementById('networkDetail'), empty=document.getElementById('networkEmpty');
  if(!svg||!viewport||!edgesLayer||!nodesLayer||!stage)return;

  const NS='http://www.w3.org/2000/svg',W=1800,H=1100;
  const bySlug=new Map(data.nodes.map(n=>[n.slug,n]));
  const baseEdges=data.edges.filter(e=>bySlug.has(e.source)&&bySlug.has(e.target));
  const historyEdges=(data.historical_edges||[]).filter(e=>bySlug.has(e.source)&&bySlug.has(e.target));
  let historyAt=null;
  const activeHistory=()=>historyEdges.filter(e=>(e.start_sort==null||Number(e.start_sort)<=historyAt)&&(e.end_sort==null||Number(e.end_sort)>=historyAt));
  const allEdges=[...baseEdges,...historyEdges];
  const totalDegree=new Map(data.nodes.map(n=>[n.slug,0]));
  allEdges.forEach(e=>{ totalDegree.set(e.source,(totalDegree.get(e.source)||0)+1); totalDegree.set(e.target,(totalDegree.get(e.target)||0)+1); });
  const chapters=[...new Set(data.nodes.map(n=>n.chapter||'Setting'))].sort((a,b)=>a.localeCompare(b));
  const chapterSel=document.getElementById('networkChapter');
  chapters.forEach(c=>chapterSel?.insertAdjacentHTML('beforeend',`<option value="${escAttr(c)}">${esc(c)}</option>`));

  let mode='story',chapter='all',query='',selected=null,visibleNodes=[],visibleEdges=[];
  let view={x:0,y:0,s:1};
  const pointers=new Map();
  let dragStart=null,pinchStart=null;

  function storyEdges(){
    const explicit=allEdges.filter(e=>e.explicit);
    const automatic=allEdges.filter(e=>!e.explicit);
    const entities=data.nodes.filter(n=>n.level==='entity');
    if(!entities.length){
      // Old/simple projects may have no entity headings. Keep the graph useful,
      // but choose the strongest references instead of drawing a hairball.
      return [...explicit,...automatic.sort((a,b)=>((totalDegree.get(b.source)||0)+(totalDegree.get(b.target)||0))-((totalDegree.get(a.source)||0)+(totalDegree.get(a.target)||0))).slice(0,80)];
    }
    const chosen=[...explicit];
    const seen=new Set(explicit.map(edgeKey));
    let automaticCount=0;
    const rankedEntities=[...entities].sort((a,b)=>(totalDegree.get(b.slug)||0)-(totalDegree.get(a.slug)||0));
    for(const entity of rankedEntities){
      if(automaticCount>=140)break;
      const refs=automatic.filter(e=>e.source===entity.slug||e.target===entity.slug).sort((a,b)=>{
        const ao=a.source===entity.slug?a.target:a.source, bo=b.source===entity.slug?b.target:b.source;
        const an=bySlug.get(ao),bn=bySlug.get(bo);
        // Prefer entity-to-entity links, then less generic/less hyper-connected pages.
        const as=(an?.level==='entity'?100:0)-Math.min(40,totalDegree.get(ao)||0);
        const bs=(bn?.level==='entity'?100:0)-Math.min(40,totalDegree.get(bo)||0);
        return bs-as;
      });
      for(const e of refs.slice(0,6)){const k=edgeKey(e);if(!seen.has(k)&&automaticCount<140){chosen.push(e);seen.add(k);automaticCount++}}
    }
    return chosen;
  }
  function edgeKey(e){return `${[e.source,e.target].sort().join('|')}|${e.explicit?'x':'r'}|${e.relation||''}`}
  function modeEdges(){
    const currentBase=baseEdges;
    let edges=mode==='historical'?(historyAt==null?historyEdges:activeHistory()):mode==='relationships'?currentBase.filter(e=>e.explicit):mode==='story'?storyEdges().filter(e=>e.kind!=='historical'):currentBase;

    if(chapter!=='all')edges=edges.filter(e=>bySlug.get(e.source)?.chapter===chapter||bySlug.get(e.target)?.chapter===chapter);
    return edges;
  }
  function build(){
    visibleEdges=modeEdges();
    const active=new Set(); visibleEdges.forEach(e=>{active.add(e.source);active.add(e.target)});
    if(query){for(const n of data.nodes){if((n.title+' '+n.chapter).toLowerCase().includes(query))active.add(n.slug)}}
    visibleNodes=data.nodes.filter(n=>active.has(n.slug));
    if(query){
      const matches=new Set(visibleNodes.filter(n=>(n.title+' '+n.chapter).toLowerCase().includes(query)).map(n=>n.slug));
      const neighborhood=new Set(matches);
      visibleEdges.forEach(e=>{if(matches.has(e.source)||matches.has(e.target)){neighborhood.add(e.source);neighborhood.add(e.target)}});
      visibleNodes=visibleNodes.filter(n=>neighborhood.has(n.slug));
      visibleEdges=visibleEdges.filter(e=>neighborhood.has(e.source)&&neighborhood.has(e.target));
    }
    layout();draw();
    if(!selected||!visibleNodes.some(n=>n.slug===selected))selected=null;
    renderDetail();
    empty?.classList.toggle('hidden',visibleEdges.length>0||visibleNodes.length>0);
  }

  function layout(){
    const groups=new Map();
    visibleNodes.forEach(n=>{const k=n.chapter||'Setting';if(!groups.has(k))groups.set(k,[]);groups.get(k).push(n)});
    const gs=[...groups.entries()],cx=W/2,cy=H/2;
    // A rectangular constellation gives chapters their own breathing room instead
    // of forcing hundreds of entries around one circular rim.
    const cols=Math.max(1,Math.ceil(Math.sqrt(gs.length*W/H))),rows=Math.max(1,Math.ceil(gs.length/cols));
    const cellW=W/cols,cellH=H/rows;
    gs.forEach(([name,nodes],gi)=>{
      const col=gi%cols,row=Math.floor(gi/cols),gx=cellW*(col+.5),gy=cellH*(row+.5);
      nodes.sort((a,b)=>(b.level==='entity')-(a.level==='entity')||(totalDegree.get(b.slug)||0)-(totalDegree.get(a.slug)||0));
      nodes.forEach((n,i)=>{const a=i*2.399963229728653,rad=34*Math.sqrt(i);n.x=gx+Math.cos(a)*rad;n.y=gy+Math.sin(a)*rad});
    });
    const deg=new Map(visibleNodes.map(n=>[n.slug,0]));
    visibleEdges.forEach(e=>{deg.set(e.source,(deg.get(e.source)||0)+1);deg.set(e.target,(deg.get(e.target)||0)+1)});
    visibleNodes.forEach(n=>n.degree=deg.get(n.slug)||0);
    if(visibleNodes.length<=240){
      for(let it=0;it<48;it++){
        const heat=(48-it)/48;
        for(let i=0;i<visibleNodes.length;i++)for(let j=i+1;j<visibleNodes.length;j++){
          const a=visibleNodes[i],b=visibleNodes[j],dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(520,dx*dx+dy*dy),force=15000/d2*heat,inv=1/Math.sqrt(d2);
          a.x+=dx*inv*force;b.x-=dx*inv*force;a.y+=dy*inv*force;b.y-=dy*inv*force;
        }
        for(const e of visibleEdges){
          const a=bySlug.get(e.source),b=bySlug.get(e.target);if(!a||!b)continue;
          const dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy)),want=e.explicit?145:205,pull=(d-want)*.011*heat;
          a.x+=dx/d*pull;b.x-=dx/d*pull;a.y+=dy/d*pull;b.y-=dy/d*pull;
        }
      }
    }
    visibleNodes.forEach(n=>{n.x=Math.max(75,Math.min(W-75,n.x));n.y=Math.max(65,Math.min(H-65,n.y))});
  }

  function draw(){
    edgesLayer.innerHTML='';nodesLayer.innerHTML='';
    svg.querySelectorAll('defs clipPath[data-network-clip]').forEach(x=>x.remove());
    for(const e of visibleEdges){
      const a=bySlug.get(e.source),b=bySlug.get(e.target);if(!a||!b)continue;
      const l=document.createElementNS(NS,'line');l.setAttribute('x1',a.x);l.setAttribute('y1',a.y);l.setAttribute('x2',b.x);l.setAttribute('y2',b.y);l.dataset.a=a.slug;l.dataset.b=b.slug;l.classList.toggle('semantic',!!e.explicit);edgesLayer.appendChild(l);
    }
    const labelThreshold=visibleNodes.length<55?0:visibleNodes.length<100?4:8;
    for(const n of visibleNodes){
      const g=document.createElementNS(NS,'g');g.classList.add('network-node');if(n.level==='entity')g.classList.add('entity');g.dataset.slug=n.slug;g.setAttribute('transform',`translate(${n.x} ${n.y})`);
      const r=Math.max(9,Math.min(23,9+Math.sqrt(n.degree||0)*2.7+(n.level==='entity'?4:0))),c=document.createElementNS(NS,'circle');c.setAttribute('r',r);g.appendChild(c);
      if(n.image){
        const id='clip-'+Math.random().toString(36).slice(2);const defs=svg.querySelector('defs'),cp=document.createElementNS(NS,'clipPath');cp.id=id;cp.dataset.networkClip='1';const cc=document.createElementNS(NS,'circle');cc.setAttribute('r',String(Math.max(6,r-3)));cp.appendChild(cc);defs.appendChild(cp);
        const im=document.createElementNS(NS,'image');im.setAttribute('href',n.image);im.setAttribute('x',String(-(r-3)));im.setAttribute('y',String(-(r-3)));im.setAttribute('width',String((r-3)*2));im.setAttribute('height',String((r-3)*2));im.setAttribute('preserveAspectRatio','xMidYMid slice');im.setAttribute('clip-path',`url(#${id})`);g.appendChild(im);
      }
      const t=document.createElementNS(NS,'text');t.setAttribute('y',String(r+18));t.textContent=n.title;
      t.classList.toggle('always',(n.degree||0)>=labelThreshold && (visibleNodes.length<100||n.level==='entity'));
      g.appendChild(t);g.tabIndex=0;g.setAttribute('role','button');g.setAttribute('aria-label',`${n.title}, ${n.degree} connections`);
      g.onclick=()=>selectNode(n.slug);g.ondblclick=()=>location.href='/wiki/'+encodeURIComponent(n.slug);g.onmouseenter=()=>highlight(n.slug);g.onmouseleave=()=>selected?highlight(selected):clearHighlight();g.onfocus=()=>highlight(n.slug);nodesLayer.appendChild(g);
    }
    if(selected)highlight(selected);
  }

  function neighbors(slug){const out=[];for(const e of visibleEdges){if(e.source===slug)out.push({slug:e.target,edge:e});else if(e.target===slug)out.push({slug:e.source,edge:e})}return out}
  function selectNode(slug){selected=slug;highlight(slug);renderDetail()}
  function highlight(slug){const near=new Set(neighbors(slug).map(x=>x.slug));nodesLayer.querySelectorAll('.network-node').forEach(el=>{const on=el.dataset.slug===slug||near.has(el.dataset.slug);el.classList.toggle('focus',el.dataset.slug===slug);el.classList.toggle('dim',!on)});edgesLayer.querySelectorAll('line').forEach(l=>l.classList.toggle('focus',l.dataset.a===slug||l.dataset.b===slug))}
  function clearHighlight(){nodesLayer.querySelectorAll('.network-node').forEach(el=>el.classList.remove('focus','dim'));edgesLayer.querySelectorAll('line').forEach(l=>l.classList.remove('focus'))}
  function renderDetail(){
    if(!detail)return;
    if(!selected){
      detail.innerHTML=`<span class="eyebrow">NETWORK VIEW</span><h2>${mode==='historical'?`Relationships in ${historyAt==null?'all recorded periods':Math.round(historyAt)}`:mode==='relationships'?'Curated relationships':mode==='all'?'Every reference':'Story links'}</h2><p>${visibleNodes.length} connected entries · ${visibleEdges.length} visible links.</p><div class="network-density-note">${mode==='story'?'Story mode caps automatic references per entity and suppresses generic heading-to-heading noise. Use All references only when you deliberately want the complete graph.':''}</div>`;return;
    }
    const n=bySlug.get(selected),near=neighbors(selected);
    const renderRelated=(limit=10)=>{const shown=near.slice(0,limit);return `${shown.map(x=>{const other=bySlug.get(x.slug);return `<button class="network-related" data-focus-slug="${escAttr(x.slug)}"><small>${esc(x.edge.explicit?(x.edge.label||x.edge.relation||'related'):'mentioned')}</small><strong>${esc(other?.title||x.slug)}</strong></button>`}).join('')||'<span class="network-muted">No direct links in the current filter.</span>'}${near.length>limit?`<button class="network-show-more" data-network-more>Show ${near.length-limit} more connections</button>`:''}`};
    detail.innerHTML=`<span class="eyebrow">${esc(n.chapter)}</span><h2>${esc(n.title)}</h2><p>${near.length} direct ${near.length===1?'connection':'connections'} in this view.</p><a class="network-open-entry" href="/wiki/${encodeURIComponent(n.slug)}">Open Codex entry →</a><div class="network-related-list">${renderRelated()}</div>`;
    const bind=()=>detail.querySelectorAll('[data-focus-slug]').forEach(b=>b.onclick=()=>selectNode(b.dataset.focusSlug));bind();detail.querySelector('[data-network-more]')?.addEventListener('click',()=>{detail.querySelector('.network-related-list').innerHTML=renderRelated(near.length);bind()});
  }

  function render(){viewport.setAttribute('transform',`translate(${view.x} ${view.y}) scale(${view.s})`)}
  function fit(){
    if(!visibleNodes.length){view={x:0,y:0,s:1};render();return}
    const xs=visibleNodes.map(n=>n.x),ys=visibleNodes.map(n=>n.y),minx=Math.min(...xs)-90,maxx=Math.max(...xs)+90,miny=Math.min(...ys)-90,maxy=Math.max(...ys)+90;
    const s=Math.max(.25,Math.min(3,Math.min(W/(maxx-minx),H/(maxy-miny))*.9));
    view.s=s;view.x=W/(2*s)-(minx+maxx)/2;view.y=H/(2*s)-(miny+maxy)/2;render();
  }
  function screenToSvg(clientX,clientY){const r=stage.getBoundingClientRect();return{x:(clientX-r.left)/Math.max(1,r.width)*W,y:(clientY-r.top)/Math.max(1,r.height)*H}}
  function zoomAt(clientX,clientY,newScale){const m=screenToSvg(clientX,clientY),wx=m.x/view.s-view.x,wy=m.y/view.s-view.y;view.s=Math.max(.2,Math.min(4,newScale));view.x=m.x/view.s-wx;view.y=m.y/view.s-wy;render()}

  stage.addEventListener('pointerdown',e=>{
    if(e.target.closest('.network-node'))return;
    stage.setPointerCapture?.(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pointers.size===1){dragStart={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y};pinchStart=null}
    else if(pointers.size===2){const [a,b]=[...pointers.values()],mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2};pinchStart={dist:Math.hypot(a.x-b.x,a.y-b.y),scale:view.s,mid};dragStart=null}
  });
  stage.addEventListener('pointermove',e=>{
    if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pointers.size>=2&&pinchStart){const [a,b]=[...pointers.values()].slice(0,2),dist=Math.max(20,Math.hypot(a.x-b.x,a.y-b.y)),mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2};zoomAt(mid.x,mid.y,pinchStart.scale*dist/pinchStart.dist);return}
    if(dragStart&&pointers.size===1){const r=stage.getBoundingClientRect(),dx=(e.clientX-dragStart.x)/Math.max(1,r.width)*W/view.s,dy=(e.clientY-dragStart.y)/Math.max(1,r.height)*H/view.s;view.x=dragStart.vx+dx;view.y=dragStart.vy+dy;render()}
  });
  function release(e){pointers.delete(e.pointerId);dragStart=null;pinchStart=null;if(pointers.size===1){const [id,p]=[...pointers.entries()][0];dragStart={x:p.x,y:p.y,vx:view.x,vy:view.y}}}
  stage.addEventListener('pointerup',release);stage.addEventListener('pointercancel',release);
  stage.addEventListener('wheel',e=>{e.preventDefault();zoomAt(e.clientX,e.clientY,view.s*(e.deltaY<0?1.12:.89))},{passive:false});

  document.getElementById('networkFit')?.addEventListener('click',fit);
  document.getElementById('networkReset')?.addEventListener('click',()=>{selected=null;query='';const q=document.getElementById('networkSearch');if(q)q.value='';mode='story';chapter='all';document.getElementById('networkMode').value=mode;chapterSel.value='all';build();setTimeout(fit,20)});
  document.getElementById('networkMode')?.addEventListener('change',e=>{mode=e.target.value;selected=null;build();setTimeout(fit,20)});
  chapterSel?.addEventListener('change',e=>{chapter=e.target.value;selected=null;build();setTimeout(fit,20)});
  document.getElementById('networkSearch')?.addEventListener('input',e=>{query=e.target.value.trim().toLowerCase();build();if(query){const hit=visibleNodes.find(n=>(n.title+' '+n.chapter).toLowerCase().includes(query));if(hit)selectNode(hit.slug)}setTimeout(fit,20)});
  const histRange=document.getElementById('networkHistoryRange'),histLabel=document.getElementById('networkHistoryLabel'),histPlay=document.getElementById('networkHistoryPlay');let histTimer=null;
  function setHistory(value){historyAt=value==null?null:Number(value);if(histLabel)histLabel.textContent=historyAt==null?'Present':String(Math.round(historyAt));if(histRange&&historyAt!=null)histRange.value=historyAt;mode='historical';document.getElementById('networkMode').value='historical';selected=null;build();setTimeout(fit,20)}
  histRange?.addEventListener('input',e=>setHistory(e.target.value));
  document.getElementById('networkHistoryNow')?.addEventListener('click',()=>{historyAt=null;mode='relationships';document.getElementById('networkMode').value='relationships';build();setTimeout(fit,20)});
  histPlay?.addEventListener('click',()=>{if(histTimer){clearInterval(histTimer);histTimer=null;histPlay.textContent='▶';return}if(!histRange)return;histPlay.textContent='❚❚';let v=Number(histRange.value||histRange.min);histTimer=setInterval(()=>{v+=Math.max(1,(Number(histRange.max)-Number(histRange.min))/80);if(v>Number(histRange.max)){clearInterval(histTimer);histTimer=null;histPlay.textContent='▶';return}setHistory(v)},180)});
  addEventListener('resize',fit);
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);build();setTimeout(fit,30);

  function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  function escAttr(s){return esc(s).replace(/`/g,'&#96;')}
})();
