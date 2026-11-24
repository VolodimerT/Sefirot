/* Offline app shell only; never cache Supabase REST/auth or per-user cloud records. */
const CACHE='sefirot-quest-shell-v63-20261124-5';
const WHITELIST=new Set(['/','/index.html','/fixtures.js','/v5-core.js','/v5-ui.js','/v5-extra.js','/v6-radar.js','/v6-tour-seal.js','/v6-mobile.js','/v5.css','/v6-mobile.css','/autopredict.js','/autopredict.css','/icon.svg','/manifest.webmanifest']);
self.addEventListener('install',event=>{
 event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll([...WHITELIST])).then(()=>self.skipWaiting()));
});
self.addEventListener('activate',event=>{
 event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('sefirot-quest-shell-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',event=>{
 const req=event.request;
 if(req.method!=='GET')return;
 const url=new URL(req.url);
 if(url.origin!==self.location.origin||!WHITELIST.has(url.pathname))return;
 event.respondWith((async()=>{
  const cache=await caches.open(CACHE);
  try{
   const live=await fetch(req);
   if(live.ok&&live.type==='basic')await cache.put(req,live.clone());
   return live;
  }catch(err){
   const hit=await cache.match(req,{ignoreSearch:true});
   if(hit)return hit;
   if(req.mode==='navigate'){
    const fallback=await cache.match('/');
    if(fallback)return fallback;
   }
   throw err;
  }
 })());
});
