// ═══════════════════════════════════════════════════════
// NewsHub Service Worker — PWA 离线缓存核心
// ═══════════════════════════════════════════════════════

const CACHE_NAME = 'newshub-v2';

// 预缓存资源列表（核心静态资源 + 首页）
const PRECACHE_URLS = [
    '/',
    '/static/css/style.css',
    '/static/manifest.json',
    '/static/icons/icon-192.png',
    '/static/icons/icon-512.png'
];

// 离线回退页面（内联 HTML）
const OFFLINE_HTML = `
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NewsHub - 离线</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0f172a;
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            text-align: center;
        }
        .container { max-width: 400px; padding: 2rem; }
        .icon { font-size: 4rem; margin-bottom: 1rem; }
        h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
        p { color: #94a3b8; margin-bottom: 1.5rem; line-height: 1.6; }
        .btn {
            display: inline-block;
            background: #3b82f6;
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 0.5rem;
            text-decoration: none;
            font-size: 0.9rem;
            border: none;
            cursor: pointer;
        }
        .btn:hover { background: #2563eb; }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">📡</div>
        <h1>您当前处于离线状态</h1>
        <p>无法连接到服务器，请检查您的网络连接后重试。之前访问过的页面可能仍可查看。</p>
        <button class="btn" onclick="window.location.reload()">重新连接</button>
        <br><br>
        <a href="/" class="btn" style="background: #475569;">返回首页（缓存）</a>
    </div>
</body>
</html>`;


// ═══════════════════════════════════════════════════════
// 1. 安装阶段 — 预缓存关键资源
// ═══════════════════════════════════════════════════════
self.addEventListener('install', event => {
    console.log('[SW] 安装中，预缓存核心资源...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                return cache.addAll(PRECACHE_URLS);
            })
            .then(() => {
                console.log('[SW] 预缓存完成');
                return self.skipWaiting();  // 立即激活
            })
            .catch(err => {
                console.error('[SW] 预缓存失败:', err);
            })
    );
});


// ═══════════════════════════════════════════════════════
// 2. 激活阶段 — 清理旧缓存
// ═══════════════════════════════════════════════════════
self.addEventListener('activate', event => {
    console.log('[SW] 激活中，清理旧缓存...');
    event.waitUntil(
        caches.keys()
            .then(cacheNames => {
                return Promise.all(
                    cacheNames
                        .filter(name => name !== CACHE_NAME)
                        .map(name => {
                            console.log('[SW] 删除旧缓存:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => {
                console.log('[SW] 激活完成，立即控制所有页面');
                return self.clients.claim();  // 立即控制所有客户端
            })
    );
});


// ═══════════════════════════════════════════════════════
// 3. 请求拦截 — 缓存策略
// ═══════════════════════════════════════════════════════
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // 只处理 GET 请求
    if (request.method !== 'GET') return;

    // ─── API 请求：Network Only（不缓存，保证实时性）───
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(request)
                .catch(() => {
                    // API 离线时返回 JSON 错误
                    return new Response(
                        JSON.stringify({
                            error: 'offline',
                            message: '您当前处于离线状态，无法获取最新数据'
                        }),
                        {
                            status: 503,
                            headers: { 'Content-Type': 'application/json' }
                        }
                    );
                })
        );
        return;
    }

    // ─── HTML 页面：Network First（优先网络，离线用缓存）───
    if (request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(
            fetch(request)
                .then(response => {
                    // 网络请求成功，更新缓存
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then(cache => {
                        cache.put(request, responseClone);
                    });
                    return response;
                })
                .catch(() => {
                    // 网络失败，尝试从缓存获取
                    return caches.match(request)
                        .then(cachedResponse => {
                            if (cachedResponse) {
                                return cachedResponse;
                            }
                            // 缓存也没有，返回离线页面
                            return new Response(OFFLINE_HTML, {
                                headers: { 'Content-Type': 'text/html; charset=utf-8' }
                            });
                        })
                })
        );
        return;
    }

    // ─── 静态资源（CSS/JS/图片/字体）：Cache First（优先缓存）───
    event.respondWith(
        caches.match(request)
            .then(cachedResponse => {
                if (cachedResponse) {
                    return cachedResponse;
                }
                // 缓存没有，请求网络并缓存
                return fetch(request)
                    .then(response => {
                        // 只缓存成功的响应
                        if (!response || response.status !== 200) {
                            return response;
                        }
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then(cache => {
                            cache.put(request, responseClone);
                        });
                        return response;
                    })
                    .catch(() => {
                        // 静态资源离线且无缓存，返回空响应
                        return new Response('', { status: 503 });
                    });
            })
    );
});


// ═══════════════════════════════════════════════════════
// 4. 消息处理（可选：用于手动控制缓存更新）
// ═══════════════════════════════════════════════════════
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});
