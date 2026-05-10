// Лёгкая обёртка над FastAPI-эндпоинтами shorts-cutter.
// Один источник правды — отсюда вызываются все компоненты.
// Никакой завязки на React: возвращает Promise<json> или throw Error.

const BASE = ""; // same-origin; FastAPI на 127.0.0.1:8000

async function _fetch(method, path, opts = {}) {
  const init = { method, headers: {} };
  if (opts.json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.json);
  } else if (opts.form) {
    // FormData передаётся как есть (multipart) — браузер сам выставит boundary
    init.body = opts.form;
  }
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let msg;
    try { msg = (await res.json()).detail || res.statusText; }
    catch { msg = res.statusText; }
    throw new Error(`${method} ${path} → ${res.status}: ${msg}`);
  }
  // некоторые эндпоинты возвращают пустоту — устойчиво к этому
  const text = await res.text();
  if (!text) return null;
  try { return JSON.parse(text); } catch { return text; }
}

const API = {
  // ── чтение (state) ─────────────────────────────────────
  backend:           ()      => _fetch("GET", "/backend"),
  llmProviders:      ()      => _fetch("GET", "/llm/providers"),
  subtitleTemplates: ()      => _fetch("GET", "/subtitle-templates"),
  brands:            ()      => _fetch("GET", "/brands"),
  brand:             (n)     => _fetch("GET", `/brands/${encodeURIComponent(n)}`),
  prompts:           ()      => _fetch("GET", "/prompts"),
  settings:          ()      => _fetch("GET", "/settings"),
  elevenlabsCheck:   ()      => _fetch("GET", "/settings/elevenlabs/check"),
  elevenlabsVoices:  ()      => _fetch("GET", "/elevenlabs/voices"),
  jobs:              (limit = 30) => _fetch("GET", `/jobs?limit=${limit}`),
  job:               (id)    => _fetch("GET", `/jobs/${id}`),
  jobScenes:         (id, i) => _fetch("GET", `/jobs/${id}/clips/${i}/scenes`),
  publishStatus:     (plat, brand) =>
                                _fetch("GET", `/publish/${plat}/status/${encodeURIComponent(brand)}`),
  uniquenessPresets: ()      => _fetch("GET", "/uniqueness/presets"),
  audioLibrary:      ()      => _fetch("GET", "/audio-library"),
  dashboard:         ()      => _fetch("GET", "/dashboard/all"),
  improvementStats:  ()      => _fetch("GET", "/improvement/stats"),

  // ── мутации ────────────────────────────────────────────
  createJob: (payload, onUploadProgress) => {
    // payload — объект; превращаем в FormData (FastAPI ожидает Form-параметры).
    // Используем XMLHttpRequest вместо fetch чтобы ловить прогресс upload'а
    // (fetch до сих пор не поддерживает upload-progress).
    const fd = new FormData();
    Object.entries(payload).forEach(([k, v]) => {
      if (v === undefined || v === null) return;
      if (v instanceof File) fd.append(k, v);
      else fd.append(k, String(v));
    });
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/jobs", true);
      xhr.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        onUploadProgress && onUploadProgress({
          loaded: e.loaded, total: e.total,
          percent: e.loaded / e.total * 100,
        });
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText || "{}")); }
          catch { resolve({}); }
        } else {
          let msg = xhr.statusText;
          try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
          reject(new Error(`POST /jobs → ${xhr.status}: ${msg}`));
        }
      };
      xhr.onerror = () => reject(new Error("network error"));
      xhr.send(fd);
    });
  },
  deleteJob:    (id)       => _fetch("DELETE", `/jobs/${id}`),
  refreshJobMetrics: (id)  => _fetch("POST", `/jobs/${id}/metrics/refresh`),
  publishClip:  (id, i, plat, body = {}) =>
                              _fetch("POST", `/jobs/${id}/clips/${i}/publish/${plat}`, { json: body }),
  uniquifyClip: (id, i, body) =>
                              _fetch("POST", `/jobs/${id}/clips/${i}/uniquify`, { json: body }),
  regenerateEffects: (id, i, body = {}) =>
                              _fetch("POST", `/jobs/${id}/clips/${i}/regenerate-effects`, { json: body }),
  regenerateClip:    (id, i, body = {}) =>
                              _fetch("POST", `/jobs/${id}/clips/${i}/regenerate`, { json: body }),
  generateThumbnails: (id, i, body = {}) =>
                              _fetch("POST", `/jobs/${id}/clips/${i}/thumbnails/generate`, { json: body }),
  uploadAudio: (file) => {
    const fd = new FormData(); fd.append("file", file);
    return _fetch("POST", "/audio-library/upload", { form: fd });
  },
  deleteAudio:  (name)        => _fetch("DELETE", `/audio-library/${encodeURIComponent(name)}`),
  addMusic:     (id, i, body) => _fetch("POST", `/jobs/${id}/clips/${i}/add-music`, { json: body }),
  brollSearch:  (body)        => _fetch("POST", "/broll/search", { json: body }),
  addBroll:     (id, i, body) => _fetch("POST", `/jobs/${id}/clips/${i}/add-broll`, { json: body }),
  savePrompt:   (name, text) => _fetch("POST", `/prompts/${name}`,       { json: { text } }),
  resetPrompt:  (name)       => _fetch("POST", `/prompts/${name}/reset`),
  saveSettings: (body)       => _fetch("POST", "/settings",              { json: body }),
  patchSubtitleTemplate: (key, patch) =>
                              _fetch("PATCH", `/subtitle-templates/${encodeURIComponent(key)}`, { json: patch }),
  resetSubtitleTemplate: (key) =>
                              _fetch("POST", `/subtitle-templates/${encodeURIComponent(key)}/reset`),
  createSubtitleTemplate: (body) =>
                              _fetch("POST", "/subtitle-templates", { json: body }),
  deleteSubtitleTemplate: (key) =>
                              _fetch("DELETE", `/subtitle-templates/${encodeURIComponent(key)}`),
  uploadYTSecrets: (brand, file) => {
    const fd = new FormData(); fd.append("file", file);
    return _fetch("POST", `/publish/youtube/upload-secrets/${encodeURIComponent(brand)}`, { form: fd });
  },
  createBrand:  (body)       => _fetch("POST", "/brands",                { json: body }),
  patchBrand:   (n, patch)   => _fetch("PATCH", `/brands/${encodeURIComponent(n)}`, { json: patch }),
  deleteBrand:  (n)          => _fetch("DELETE", `/brands/${encodeURIComponent(n)}`),
  uploadWatermark: (n, file) => {
    const fd = new FormData(); fd.append("file", file);
    return _fetch("POST", `/brands/${encodeURIComponent(n)}/watermark`, { form: fd });
  },
  uploadFaceOverlay: (n, file) => {
    const fd = new FormData(); fd.append("file", file);
    return _fetch("POST", `/brands/${encodeURIComponent(n)}/face-overlay`, { form: fd });
  },
  publishConnect:    (plat, brand, body = {}) =>
                              _fetch("POST", `/publish/${plat}/connect/${encodeURIComponent(brand)}`, { json: body }),
  publishDisconnect: (plat, brand) =>
                              _fetch("POST", `/publish/${plat}/disconnect/${encodeURIComponent(brand)}`),

  // ── ассеты ─────────────────────────────────────────────
  clipUrl: (id, file)         => `/clips/${id}/${file}`,
  thumbUrl: (id, rest)        => `/clips/${id}/thumbs/${rest}`,
};

// WebSocket для стрима прогресса нарезки.
// onMessage(line) — будет вызвано на каждое событие прогресса; line = {stage, progress, msg, eta_s, ...}.
// Возвращает функцию-теардаун, которую нужно вызвать чтобы закрыть сокет.
function openJobStream(jobId, { onMessage, onClose, onError }) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws/${jobId}`);
  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data)); }
    catch { onMessage({ stage: "raw", msg: e.data }); }
  };
  ws.onerror = (e) => onError && onError(e);
  ws.onclose = () => onClose && onClose();
  return () => { try { ws.close(); } catch {} };
}

window.API = API;
window.openJobStream = openJobStream;
