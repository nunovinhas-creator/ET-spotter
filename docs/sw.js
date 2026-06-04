/* ET-Spotter Service Worker — cache-first para o dashboard, push handler para alertas */

const CACHE_VERSION = 'et-spotter-1780587217';
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
      tag:     data.tag     || 'et-spotter-1780587217',
      data:    data,
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow('./'));
});
