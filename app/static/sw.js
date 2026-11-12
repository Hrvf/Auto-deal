// Service worker : met en cache uniquement les fichiers statiques (jamais les pages privées).
const CACHE = "autodeal-static-v1";
const ASSETS = ["/static/css/app.css", "/static/js/app.js", "/static/icon-192.png", "/static/offline.html"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    // Statique : réseau d'abord, cache en secours
    e.respondWith(fetch(req).then((r) => {
      const copy = r.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
      return r;
    }).catch(() => caches.match(req)));
  } else if (req.mode === "navigate") {
    // Pages : toujours le réseau (données privées) ; page hors ligne si pas de connexion
    e.respondWith(fetch(req).catch(() => caches.match("/static/offline.html")));
  }
});
