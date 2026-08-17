/* ET-Spotter Service Worker — network-first para o dashboard, push handler para alertas */

const CACHE_VERSION = 'et-spotter-1786976246';
const CACHE_URLS    = ['./index.html'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_VERSION)
      .then(c => c.addAll(CACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  /* Para o index.html: network-first → sempre busca a versão mais recente,
     fallback para cache apenas se offline */
  if (url.pathname.endsWith('/') || url.pathname.endsWith('index.html')) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then(c => c.put(e.request, copy));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }
  /* Para tudo o resto: cache-first (assets estáticos) */
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : { title: 'ET-Spotter', body: 'Novo alerta técnico.' };
  e.waitUntil(
    self.registration.showNotification(data.title || 'ET-Spotter', {
      body:    data.body    || '',
      icon:    './icon-192.png',
      badge:   './icon-192.png',
      tag:     data.tag     || 'et-spotter-1786976246',
      data:    data,
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow('./'));
});
