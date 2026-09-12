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
