// Minimal service worker: makes the page installable and lets the app shell open offline.
// Data (/api/*) is NEVER cached: a stale number on a trading dashboard is worse than an error.
const SHELL = "ta-shell-v1";
const FILES = ["/", "/icon-192.png", "/icon-512.png", "/manifest.webmanifest"];
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;   // data: network only
  e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(SHELL).then(x => x.put(e.request, c)); return r; })
                                .catch(() => caches.match(e.request)));   // shell: network first, cache as fallback
});
