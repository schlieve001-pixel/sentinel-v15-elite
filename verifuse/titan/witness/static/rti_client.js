/**
 * VERIFUSE FIELD UNIT — RTI Client v3.0
 * Patent Application #63/923,069
 *
 * Real SHA-256 via WebCrypto | Offline Queue via IndexedDB | Background Sync
 */

// ─── STATE ───
const SENSORS = { mag: { alpha: 0, beta: 0, gamma: 0 }, acc: { x: 0, y: 0, z: 0 } };

// ─── LOGGING ───
function appendLog(msg) {
    const el = document.getElementById("log");
    const lines = el.innerText.split("\n");
    if (lines.length > 12) lines.shift();
    lines.push(msg);
    el.innerText = lines.join("\n");
}

// ─── CRYPTO: SHA-256 via WebCrypto ───
async function sha256(data) {
    const buf = new TextEncoder().encode(data);
    const hash = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Blob(blob) {
    const buf = await blob.arrayBuffer();
    const hash = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
}

// ─── JCS: RFC 8785 Canonical JSON ───
function jcs(obj) {
    if (obj === null || obj === undefined) return "null";
    if (typeof obj === "boolean" || typeof obj === "number") return JSON.stringify(obj);
    if (typeof obj === "string") return JSON.stringify(obj);
    if (Array.isArray(obj)) return "[" + obj.map(jcs).join(",") + "]";
    if (typeof obj === "object") {
        const keys = Object.keys(obj).sort();
        return "{" + keys.map(k => JSON.stringify(k) + ":" + jcs(obj[k])).join(",") + "}";
    }
    return JSON.stringify(String(obj));
}

async function sha256Dict(obj) {
    return sha256(jcs(obj));
}

// ─── OFFLINE QUEUE (IndexedDB) ───
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

async function enqueue(payload) {
    const db = await openQueue();
    return new Promise((resolve, reject) => {
        const tx = db.transaction("queue", "readwrite");
        const store = tx.objectStore("queue");
        const req = store.add({ payload, queued_at: new Date().toISOString() });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function getQueueCount() {
    const db = await openQueue();
    return new Promise((resolve) => {
        const tx = db.transaction("queue", "readonly");
        const req = tx.objectStore("queue").count();
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(0);
    });
}

async function updateQueueBadge() {
    const count = await getQueueCount();
    const badge = document.getElementById("queue-badge");
    if (count > 0) {
        badge.innerText = count + " QUEUED";
        badge.style.display = "block";
    } else {
        badge.style.display = "none";
    }
}

// ─── SENSORS ───
async function activateSensors() {
    if (typeof DeviceOrientationEvent !== "undefined" && typeof DeviceOrientationEvent.requestPermission === "function") {
        try { await DeviceOrientationEvent.requestPermission(); } catch (e) { /* denied */ }
    }
    if (typeof DeviceMotionEvent !== "undefined" && typeof DeviceMotionEvent.requestPermission === "function") {
        try { await DeviceMotionEvent.requestPermission(); } catch (e) { /* denied */ }
    }
    window.addEventListener("deviceorientation", (e) => {
        SENSORS.mag = { alpha: e.alpha || 0, beta: e.beta || 0, gamma: e.gamma || 0 };
        document.getElementById("mag-val").innerText = "MAG: " + (e.alpha || 0).toFixed(0) + "\u00b0";
    });
    window.addEventListener("devicemotion", (e) => {
        const a = e.acceleration || {};
        SENSORS.acc = { x: a.x || 0, y: a.y || 0, z: a.z || 0 };
        const total = Math.sqrt(SENSORS.acc.x ** 2 + SENSORS.acc.y ** 2 + SENSORS.acc.z ** 2);
        document.getElementById("acc-val").innerText = "ACC: " + total.toFixed(1) + "G";
    });

    appendLog("SENSORS ONLINE.");
    document.getElementById("btn-capture").innerText = "INITIATE RITUAL";
    document.getElementById("btn-capture").onclick = performRitual;
}

// ─── THE RITUAL ───
async function performRitual() {
    const btn = document.getElementById("btn-capture");
    btn.disabled = true;

    try {
        // STEP 1: Environment Snapshot
        btn.innerText = "ENVIRONMENT...";
        appendLog("[1/5] Capturing environment...");
        const now = new Date();
        const magMagnitude = Math.sqrt(SENSORS.mag.alpha ** 2 + SENSORS.mag.beta ** 2 + SENSORS.mag.gamma ** 2);

        const environment = {
            timestamp_iso: now.toISOString(),
            timestamp_ms: now.getTime(),
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            user_agent: navigator.userAgent,
            platform: navigator.platform || "unknown",
            language: navigator.language || "en",
            screen: {
                width: window.screen.width,
                height: window.screen.height,
                pixel_ratio: window.devicePixelRatio || 1,
                color_depth: window.screen.colorDepth || 24
            },
            camera: null,
            magnetic_field: {
                x: SENSORS.mag.alpha,
                y: SENSORS.mag.beta,
                z: SENSORS.mag.gamma,
                magnitude: magMagnitude
            },
            acceleration: { x: SENSORS.acc.x, y: SENSORS.acc.y, z: SENSORS.acc.z },
            connection: null
        };

        // Camera info
        const video = document.getElementById("preview");
        if (video.srcObject) {
            const track = video.srcObject.getVideoTracks()[0];
            const settings = track ? track.getSettings() : {};
            environment.camera = {
                width: settings.width || video.videoWidth || 1920,
                height: settings.height || video.videoHeight || 1080,
                facing: settings.facingMode || "environment",
                device_id: (settings.deviceId || "unknown").substring(0, 16)
            };
        }

        // Connection info
        if (navigator.connection) {
            environment.connection = {
                type: navigator.connection.effectiveType || "unknown",
                downlink: navigator.connection.downlink || 0
            };
        }

        // STEP 2: Strobe Flash
        btn.innerText = "PHOTON BIND...";
        appendLog("[2/5] Active Photon Binding...");
        const strobeTimestamps = [];
        const videoTrack = video.srcObject ? video.srcObject.getVideoTracks()[0] : null;
        const hasTorch = videoTrack && videoTrack.getCapabilities && videoTrack.getCapabilities().torch;

        for (let i = 0; i < 4; i++) {
            const state = i % 2 === 0 ? "on" : "off";
            strobeTimestamps.push({ state, t: Date.now() });
            if (hasTorch) {
                try { await videoTrack.applyConstraints({ advanced: [{ torch: state === "on" }] }); } catch (_) {}
            } else {
                document.body.style.background = state === "on" ? "#fff" : "#000";
            }
            await new Promise(r => setTimeout(r, 80));
        }
        document.body.style.background = "#000";

        // STEP 3: Capture Frame
        btn.innerText = "CAPTURING...";
        appendLog("[3/5] Frame capture...");
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth || 1920;
        canvas.height = video.videoHeight || 1080;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0);
        // Burn timestamp
        ctx.fillStyle = "rgba(0,0,0,0.5)";
        ctx.fillRect(0, canvas.height - 30, canvas.width, 30);
        ctx.fillStyle = "#00ff41";
        ctx.font = "14px monospace";
        ctx.fillText("VF-RTI " + now.toISOString(), 10, canvas.height - 10);

        const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.85));

        // STEP 4: Air Signature
        btn.innerText = "AIR SIGNATURE...";
        appendLog("[4/5] Recording gesture trace...");
        const gestureTrace = [];
        for (let i = 0; i < 20; i++) {
            gestureTrace.push({
                t: i * 50.0,
                ax: SENSORS.acc.x, ay: SENSORS.acc.y, az: SENSORS.acc.z,
                gx: 0, gy: 0, gz: 0
            });
            await new Promise(r => setTimeout(r, 50));
        }

        // STEP 5: Compute Hashes
        btn.innerText = "HASHING...";
        appendLog("[5/5] Computing fusion hash...");

        const h0 = await sha256Dict(environment);
        const h1 = await sha256Blob(blob);

        const magForH2 = {
            x: SENSORS.mag.alpha,
            y: SENSORS.mag.beta,
            z: SENSORS.mag.gamma,
            magnitude: magMagnitude,
            strobe_timestamps: strobeTimestamps
        };
        const h2 = await sha256Dict(magForH2);
        const h3 = await sha256Dict(gestureTrace);
        const h5 = await sha256Dict({ h0_seed: h0, h1_media: h1, h2_magnetic: h2, h3_gesture: h3 });

        appendLog("H5: " + h5.substring(0, 16) + "...");

        // Build FuseMoment payload (matches Judge schema exactly)
        const payload = {
            protocol_version: "3.0",
            witness_id: "FIELD-UNIT-" + (environment.camera ? environment.camera.device_id.substring(0, 6) : "ANON"),
            timestamp_iso: now.toISOString(),
            timestamp_ms: now.getTime(),
            environment: environment,
            hashes: { h0_seed: h0, h1_media: h1, h2_magnetic: h2, h3_gesture: h3, h5_fused: h5 },
            magnetic_field: { x: SENSORS.mag.alpha, y: SENSORS.mag.beta, z: SENSORS.mag.gamma, magnitude: magMagnitude },
            gesture_trace: gestureTrace,
            strobe_timestamps: strobeTimestamps,
            camera: environment.camera
        };

        // ─── TRANSMIT OR QUEUE ───
        btn.innerText = "TRANSMITTING...";
        if (navigator.onLine) {
            try {
                const resp = await fetch("/seal", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const result = await resp.json();
                if (result.status === "SECURED") {
                    appendLog("SECURED. Vault #" + result.vault_index + " | " + result.verdict);
                    btn.innerText = "SECURED";
                    btn.style.borderColor = "#00ff41";
                } else {
                    appendLog("RESULT: " + (result.verdict || result.reason || "UNKNOWN"));
                    btn.innerText = result.verdict || "DONE";
                }
            } catch (e) {
                appendLog("NETWORK FAIL. Queuing offline...");
                await enqueue(payload);
                await updateQueueBadge();
                btn.innerText = "QUEUED OFFLINE";
                btn.style.borderColor = "#ff8800";
            }
        } else {
            appendLog("OFFLINE. Evidence queued for sync.");
            await enqueue(payload);
            await updateQueueBadge();
            btn.innerText = "QUEUED OFFLINE";
            btn.style.borderColor = "#ff8800";
        }
    } catch (err) {
        appendLog("ERROR: " + err.message);
        btn.innerText = "ERROR";
    }

    btn.disabled = false;
    setTimeout(() => {
        btn.innerText = "INITIATE RITUAL";
        btn.style.borderColor = "#00ff41";
        btn.onclick = performRitual;
    }, 3000);
}

// ─── BOOT ───
navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 3840 }, height: { ideal: 2160 } } })
    .then(s => { document.getElementById("preview").srcObject = s; appendLog("CAMERA ONLINE."); })
    .catch(() => appendLog("CAMERA DENIED."));

document.getElementById("btn-capture").onclick = activateSensors;
updateQueueBadge();
