const CACHE_NAME = 'fleasodapos-v1';
const ASSETS = [
    '/',
    '/static/logo.png',
    '/static/src/styles.css',
    'https://cdn.tailwindcss.com',
    'https://unpkg.com/htmx.org@1.9.10',
    '//unpkg.com/alpinejs'
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(ASSETS))
    );
});

self.addEventListener('fetch', (event) => {
    event.respondWith(
        fetch(event.request)
            .catch(() => caches.match(event.request))
    );
});
