const STATIC='seeker-static-v4400';
const PRIVATE='seeker-private-v4400';
const META='seeker-offline-meta-v4400';
const ENABLE_KEY='/__seeker_offline_enabled__';
const SHELL=['/static/wiki.css?v=4400','/static/wiki.js?v=4400','/static/tour.css?v=4400','/static/tour.js?v=4400','/static/seeker-icon.svg','/static/icon-192.png','/static/icon-512.png'];
const privatePage=u=>u.pathname==='/'||['/session','/timeline','/calendar','/mysteries','/handouts','/updates','/network','/characters','/campaign','/structures','/archive','/schedule','/tables'].includes(u.pathname)||u.pathname.startsWith('/wiki/')||u.pathname.startsWith('/atlas/')||u.pathname.startsWith('/handout/')||u.pathname.startsWith('/characters/');
const privateAsset=u=>u.pathname.startsWith('/project-asset/')||u.pathname.startsWith('/uploads/');
async function offlineEnabled(){const c=await caches.open(META);return !!(await c.match(ENABLE_KEY))}
async function enableOffline(){const c=await caches.open(META);await c.put(ENABLE_KEY,new Response('1'));return true}
async function disableOffline(){await caches.delete(PRIVATE);const c=await caches.open(META);await c.delete(ENABLE_KEY);return true}
self.addEventListener('install',e=>e.waitUntil(caches.open(STATIC).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>{
  const oldSeeker=(k.startsWith('seeker-static-')&&k!==STATIC)||(k.startsWith('seeker-private-')&&k!==PRIVATE)||(k.startsWith('seeker-offline-meta-')&&k!==META);
  const oldLoreforge=k.startsWith('loreforge-static-')||k.startsWith('loreforge-private-')||k.startsWith('loreforge-offline-meta-');
  return oldSeeker||oldLoreforge;
}).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin)return;
  // Deployed static files are network-first so an old service worker can never
  // pin a stale JS bundle after an upgrade. The versioned cache is only fallback.
  if(u.pathname.startsWith('/static/')){e.respondWith(fetch(e.request).then(r=>{if(r.ok){const copy=r.clone();caches.open(STATIC).then(c=>c.put(e.request,copy))}return r}).catch(()=>caches.match(e.request)));return}
  if(privatePage(u)||privateAsset(u)){
    e.respondWith((async()=>{
      const enabled=await offlineEnabled();
      try{
        const r=await fetch(e.request);
        // Invitation-protected campaign data is cached only by explicit player
        // opt-in. Never persist redirects/login gates/error responses.
        const type=r.headers.get('content-type')||'';
        const cacheablePage=privatePage(u)&&type.includes('text/html');
        const cacheableAsset=privateAsset(u)&&(type.startsWith('image/')||type.startsWith('audio/')||type==='application/pdf');
        if(enabled&&r.ok&&!r.redirected&&(cacheablePage||cacheableAsset)){const c=await caches.open(PRIVATE);await c.put(e.request,r.clone())}
        return r;
      }catch(err){
        if(enabled){const hit=await caches.match(e.request);if(hit)return hit;if(privatePage(u)){const home=await caches.match('/');if(home)return home}}
        throw err;
      }
    })());
  }
});
self.addEventListener('message',e=>{
  if(e.data==='OFFLINE_ON')e.waitUntil(enableOffline());
  if(e.data==='OFFLINE_OFF'||e.data==='CLEAR_PRIVATE')e.waitUntil(disableOffline());
});
