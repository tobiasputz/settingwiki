(()=>{
'use strict';
/*
 * Seeker UI Core
 * A deliberately tiny navigation safety net. Feature scripts still own their
 * richer behavior; this only guarantees that visible tab buttons can always
 * reveal their matching pane, even when another module throws during startup.
 */
const GROUPS=[
  {button:'[data-living-tab]',buttonKey:'livingTab',pane:'[data-living-pane]',paneKey:'livingPane'},
  {button:'[data-player-tab]',buttonKey:'playerTab',pane:'[data-player-pane]',paneKey:'playerPane'},
  {button:'[data-la-tab]',buttonKey:'laTab',pane:'[data-la-pane]',paneKey:'laPane'},
  {button:'[data-v8-tab]',buttonKey:'v8Tab',pane:'[data-v8-pane]',paneKey:'v8Pane'},
  {button:'[data-v7-tab]',buttonKey:'v7Tab',pane:'[data-v7-pane]',paneKey:'v7Pane'},
  {button:'[data-cc-tab]',buttonKey:'ccTab',pane:'.cc-pane',paneIdPrefix:'cc-'}
];
const all=s=>[...document.querySelectorAll(s)];
function paneFor(group,name){
  if(group.paneIdPrefix)return document.getElementById(group.paneIdPrefix+name);
  return all(group.pane).find(p=>p.dataset[group.paneKey]===name)||null;
}
function activate(group,name,{hash=true}={}){
  const button=all(group.button).find(b=>b.dataset[group.buttonKey]===name);
  const pane=paneFor(group,name);
  if(!button||!pane)return false;
  all(group.button).forEach(b=>{
    const on=b===button;b.classList.toggle('active',on);b.setAttribute('aria-selected',on?'true':'false');
  });
  all(group.pane).forEach(p=>p.classList.toggle('active',p===pane));
  if(hash&&location.hash!==`#${name}`){try{history.replaceState(null,'',`#${name}`)}catch(_){}}
  return true;
}
function groupForButton(button){return GROUPS.find(g=>button.matches(g.button));}
function applyHash(){
  const name=decodeURIComponent((location.hash||'').slice(1));if(!name)return;
  for(const group of GROUPS){if(activate(group,name,{hash:false}))break;}
  // Studio workspaces use ids rather than pane data attributes.
  const studio=document.getElementById('workspace-'+name),studioButton=all('[data-workspace]').find(b=>b.dataset.workspace===name);
  if(studio&&studioButton){all('[data-workspace]').forEach(b=>b.classList.toggle('active',b===studioButton));all('.workspace').forEach(p=>p.classList.toggle('active',p===studio));}
}
document.addEventListener('click',event=>{
  const button=event.target.closest?.('button');if(!button)return;
  const group=groupForButton(button);if(!group)return;
  const name=button.dataset[group.buttonKey];
  // Run after the feature-specific handler. If that handler succeeded this is
  // a no-op; if it never bound (or a previous init step threw), navigation
  // still works.
  queueMicrotask(()=>{const pane=paneFor(group,name);if(pane&&!pane.classList.contains('active'))activate(group,name);});
});
addEventListener('hashchange',applyHash);
setTimeout(applyHash,0);
window.SeekerUICore={activateTab:(name)=>{for(const group of GROUPS)if(activate(group,name))return true;return false;},applyHash};
})();

/* V10 shared UI primitives. Kept additive so every existing feature dialog and
   drawer continues to behave exactly as it did in 9.x. */
(()=>{
'use strict';
if(window.SeekerUI)return;
const esc=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function toast(message,{tone='normal',timeout=2800}={}){
  let stack=document.getElementById('seekerSharedToasts');
  if(!stack){stack=document.createElement('div');stack.id='seekerSharedToasts';stack.className='seeker-shared-toasts';document.body.appendChild(stack)}
  const item=document.createElement('div');item.className=`seeker-shared-toast ${tone}`;item.textContent=String(message||'');stack.appendChild(item);
  requestAnimationFrame(()=>item.classList.add('show'));setTimeout(()=>{item.classList.remove('show');setTimeout(()=>item.remove(),180)},timeout);
  return item;
}
function closeDialog(dialog){if(!dialog)return;dialog.classList.remove('open');dialog.setAttribute('aria-hidden','true');setTimeout(()=>dialog.remove(),180)}
function dialog({title='Seeker',eyebrow='',body='',actions=[]}={}){
  const wrap=document.createElement('div');wrap.className='seeker-shared-dialog';wrap.setAttribute('role','dialog');wrap.setAttribute('aria-modal','true');wrap.setAttribute('aria-hidden','false');
  wrap.innerHTML=`<div class="seeker-shared-dialog-card"><header><div>${eyebrow?`<small>${esc(eyebrow)}</small>`:''}<strong>${esc(title)}</strong></div><button type="button" data-shared-close aria-label="Close">×</button></header><div class="seeker-shared-dialog-body"></div><footer></footer></div>`;
  const bodyHost=wrap.querySelector('.seeker-shared-dialog-body');if(typeof body==='string')bodyHost.innerHTML=body;else if(body instanceof Node)bodyHost.appendChild(body);
  const footer=wrap.querySelector('footer');actions.forEach(action=>{const b=document.createElement('button');b.type='button';b.className=action.className||'seeker-shared-button';b.textContent=action.label||'OK';b.addEventListener('click',()=>action.onClick?.(wrap,b));footer.appendChild(b)});
  wrap.querySelector('[data-shared-close]').onclick=()=>closeDialog(wrap);wrap.addEventListener('mousedown',e=>{if(e.target===wrap)closeDialog(wrap)});document.body.appendChild(wrap);requestAnimationFrame(()=>wrap.classList.add('open'));return wrap;
}
function busy(button,promise){if(button)button.disabled=true;return Promise.resolve(promise).finally(()=>{if(button)button.disabled=false})}
function confirmDialog(message,{title='Confirm',confirmLabel='Confirm',danger=false}={}){
  return new Promise(resolve=>{const body=document.createElement('p');body.textContent=String(message||'');let settled=false;const finish=(value,w)=>{if(settled)return;settled=true;closeDialog(w);resolve(value)};const w=dialog({title,body,actions:[{label:'Cancel',onClick:x=>finish(false,x)},{label:confirmLabel,className:danger?'seeker-shared-button danger':'primary',onClick:x=>finish(true,x)}]});w.querySelector('[data-shared-close]').onclick=()=>finish(false,w)});
}
function drawer({id='',className='',content=''}={}){let el=id&&document.getElementById(id);if(!el){el=document.createElement('aside');if(id)el.id=id;el.className=`seeker-ui-drawer ${className}`.trim();document.body.appendChild(el)}if(typeof content==='string')el.innerHTML=content;else if(content instanceof Node){el.replaceChildren(content)};requestAnimationFrame(()=>el.classList.add('open'));el.setAttribute('aria-hidden','false');return el}
function closeDrawer(el){if(typeof el==='string')el=document.getElementById(el);el?.classList.remove('open');el?.setAttribute('aria-hidden','true')}
function tabs(root,{button='[data-ui-tab]',pane='[data-ui-pane]',activeClass='active'}={}){if(typeof root==='string')root=document.querySelector(root);if(!root)return()=>{};const activate=name=>{root.querySelectorAll(button).forEach(b=>b.classList.toggle(activeClass,String(b.dataset.uiTab)===String(name)));root.querySelectorAll(pane).forEach(p=>p.classList.toggle(activeClass,String(p.dataset.uiPane)===String(name)))};root.addEventListener('click',e=>{const b=e.target.closest(button);if(b)activate(b.dataset.uiTab)});return activate}
function statusChip(text,tone=''){return `<span class="seeker-ui-status ${esc(tone)}">${esc(text)}</span>`}
function empty(message){return `<div class="seeker-ui-empty">${esc(message||'Nothing here yet.')}</div>`}
window.SeekerUI={toast,dialog,closeDialog,confirm:confirmDialog,drawer,closeDrawer,tabs,statusChip,empty,busy,escape:esc};
})();
