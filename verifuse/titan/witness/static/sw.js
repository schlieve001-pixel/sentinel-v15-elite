/**
 * VERIFUSE FIELD UNIT — Service Worker
 * Strategy: Network-First, Fallback-to-Cache
 * Offline Queue: Pending evidence stored in IndexedDB, auto-synced on reconnect
 */

const CACHE_NAME = "verifuse-titan-v1";
const SHELL_ASSETS = ["/", "/rti_client.js", "/manifest.json"];

// ─── INSTALL: Pre-cache shell ───
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

// ─── ACTIVATE: Purge old caches ───
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ─── FETCH: Network-first, cache fallback ───
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Don't cache API calls — those go through the offline queue in the client
  if (url.pathname === "/seal" || url.pathname.startsWith("/verify") || url.pathname.startsWith("/append")) {
    return;
  }

  e.respondWith(
    fetch(e.request)
      .then((response) => {
        // Clone and cache successful responses
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(e.request))
  );
});

// ─── SYNC: Flush offline queue when connection restores ───
self.addEventListener("sync", (e) => {
  if (e.tag === "flush-evidence-queue") {
    e.waitUntil(flushOfflineQueue());
  }
});

async function flushOfflineQueue() {
  const db = await openQueue();
  const tx = db.transaction("queue", "readonly");
  const store = tx.objectStore("queue");
  const items = await idbGetAll(store);

  for (const item of items) {
    try {
      const resp = await fetch("/seal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item.payload),
      });
      if (resp.ok) {
        const delTx = db.transaction("queue", "readwrite");
        delTx.objectStore("queue").delete(item.id);
        await idbCommit(delTx);
        notifyClients({ type: "SYNCED", id: item.id });
      }
    } catch (_) {
      break; // Still offline, stop trying
    }
  }
}

// ─── MESSAGE: Manual flush trigger from client ───
self.addEventListener("message", (e) => {
  if (e.data && e.data.type === "FLUSH_QUEUE") {
    flushOfflineQueue().then(() => {
      notifyClients({ type: "FLUSH_COMPLETE" });
    });
  }
});

// ─── IndexedDB Helpers ───
function openQueue() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("verifuse_queue", 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbGetAll(store) {
  return new Promise((resolve, reject) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbCommit(tx) {
  return new Promise((resolve) => {
    tx.oncomplete = resolve;
  });
}

function notifyClients(msg) {
  self.clients.matchAll().then((clients) => {
    clients.forEach((c) => c.postMessage(msg));
  });
}
