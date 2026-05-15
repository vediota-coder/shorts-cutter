// === Teleprompter screen ===
const TP_R = React;

function parseHash() {
  // #prompter?id=XXX&v=2
  const h = location.hash || "";
  const q = h.split("?")[1] || "";
  const p = new URLSearchParams(q);
  return { id: p.get("id") || "", v: parseInt(p.get("v") || "0", 10), mode: p.get("mode") || "master" };
}

function detectMime() {
  const cands = [
    "video/mp4;codecs=h264,aac",
    "video/mp4;codecs=avc1.42E01E,mp4a.40.2",
    "video/mp4",
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm"
  ];
  for (const m of cands) if (MediaRecorder.isTypeSupported(m)) return m;
  return "video/webm";
}

function fmtMime(m) {
  if (m.includes("mp4")) return "MP4 (H.264/AAC) ✓";
  if (m.includes("vp9")) return "WebM (VP9) — нужна конвертация";
  if (m.includes("vp8")) return "WebM (VP8) — нужна конвертация";
  return m;
}

function TeleprompterScreen(props) {
  // приоритет: пропсы из app.jsx, fallback на hash (для прямых ссылок и slave-режима)
  const hashParsed = parseHash();
  const VID = props?.vid || hashParsed.id;
  const vIdx = (typeof props?.vIdx === "number" ? props.vIdx : hashParsed.v) || 0;
  const mode = props?.mode || hashParsed.mode;
  const IS_SLAVE = mode === "slave";
  const ROOM = VID || "default";

  const [video, setVideo] = TP_R.useState(null);
  const [versions, setVersions] = TP_R.useState([]);
  const [versionIdx, setVersionIdx] = TP_R.useState(vIdx);
  const [text, setText] = TP_R.useState("");
  const [transcript, setTranscript] = TP_R.useState("");
  const [playing, setPlaying] = TP_R.useState(false);
  const [speed, setSpeed] = TP_R.useState(40);
  const [fontSize, setFontSize] = TP_R.useState(38);
  const [recordingState, setRecordingState] = TP_R.useState({ recording: false, dur: 0, fmt: "" });
  const [takes, setTakes] = TP_R.useState([]);
  const [cams, setCams] = TP_R.useState([]);
  const [mics, setMics] = TP_R.useState([]);
  const [camId, setCamId] = TP_R.useState("");
  const [micId, setMicId] = TP_R.useState("");
  const [aspect, setAspect] = TP_R.useState("9:16");
  const [zoom, setZoom] = TP_R.useState(1);
  const [panX, setPanX] = TP_R.useState(0);
  const [panY, setPanY] = TP_R.useState(0);
  const [opacity, setOpacity] = TP_R.useState(85);
  const [direction, setDirection] = TP_R.useState("up"); // "up" — снизу вверх (классика), "down" — сверху вниз
  const [qrUrl, setQrUrl] = TP_R.useState("");
  const [slaveLink, setSlaveLink] = TP_R.useState("");

  const scrollPosRef = TP_R.useRef(0);
  const lastFrameRef = TP_R.useRef(0);
  const directionRef = TP_R.useRef("up");
  const camStreamRef = TP_R.useRef(null);
  const videoElRef = TP_R.useRef(null);
  const scrollElRef = TP_R.useRef(null);
  const camWrapRef = TP_R.useRef(null);
  const recorderRef = TP_R.useRef(null);
  const chunksRef = TP_R.useRef([]);
  const recStartRef = TP_R.useRef(0);
  const recRafRef = TP_R.useRef(null);
  const playingRef = TP_R.useRef(false);
  const speedRef = TP_R.useRef(40);

  TP_R.useEffect(() => { playingRef.current = playing; }, [playing]);
  TP_R.useEffect(() => { speedRef.current = speed; }, [speed]);
  TP_R.useEffect(() => { directionRef.current = direction; }, [direction]);

  // refs для canvas-pipeline (читаем актуальные значения на каждом frame)
  const zoomRef = TP_R.useRef(1);
  const panXRef = TP_R.useRef(0);
  const panYRef = TP_R.useRef(0);
  const aspectRef = TP_R.useRef("9:16");
  TP_R.useEffect(() => { zoomRef.current = zoom; }, [zoom]);
  TP_R.useEffect(() => { panXRef.current = panX; }, [panX]);
  TP_R.useEffect(() => { panYRef.current = panY; }, [panY]);
  TP_R.useEffect(() => { aspectRef.current = aspect; }, [aspect]);

  // Загружаем данные шортса
  TP_R.useEffect(() => {
    if (!VID) return;
    fetch("/api/content-plan/videos").then(r => r.json()).then(cat => {
      const v = cat.videos.find(x => x.id === VID);
      if (v) setVideo(v);
    });
    fetch("/api/content-plan/rewrites").then(r => r.json()).then(rw => {
      setVersions(rw[VID] || []);
    });
    fetch(`/api/content-plan/transcript/${VID}`).then(r => r.json()).then(d => setTranscript(d.text || ""));
    // подтягиваем сохранённые дубли по этому шортсу
    fetch(`/api/teleprompter/takes?video_id=${VID}`).then(r => r.json()).then(d => {
      const arr = (d.takes || []).map(t => ({
        id: t.id,
        name: t.filename,
        dur: Math.round(t.duration || 0),
        ext: t.filename.endsWith(".mp4") ? "mp4" : "webm",
        server_url: `/api/teleprompter/takes/${t.id}/video`,
        persisted: true,
        created_at: t.created_at,
      }));
      if (arr.length) setTakes(arr);
    });
  }, [VID]);

  // выбранная версия определяет текст
  TP_R.useEffect(() => {
    if (versions[versionIdx]) {
      setText(versions[versionIdx].text);
      scrollPosRef.current = 0;
      if (scrollElRef.current) scrollElRef.current.style.transform = "translateY(0)";
    }
  }, [versions, versionIdx]);

  // tick прокрутки
  TP_R.useEffect(() => {
    let raf;
    function tick(ts) {
      if (!lastFrameRef.current) lastFrameRef.current = ts;
      const dt = (ts - lastFrameRef.current) / 1000;
      lastFrameRef.current = ts;
      if (playingRef.current) {
        scrollPosRef.current += speedRef.current * dt;
        if (scrollElRef.current) {
          // direction "up": классика — текст уходит вверх, новые строки приходят снизу
          // direction "down": текст ПЕРЕВЁРНУТ вертикально (низ=начало, верх=конец)
          //   и двигается сверху вниз — для камер над экраном
          if (directionRef.current === "down") {
            scrollElRef.current.style.transform = `scaleY(-1) translateY(${-scrollPosRef.current}px)`;
          } else {
            scrollElRef.current.style.transform = `translateY(${-scrollPosRef.current}px)`;
          }
        }
      }
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Камера: первичная инициализация + список устройств
  TP_R.useEffect(() => {
    if (IS_SLAVE) return;
    (async () => {
      try {
        await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        setCams(devices.filter(d => d.kind === "videoinput"));
        setMics(devices.filter(d => d.kind === "audioinput"));
      } catch (e) {
        console.error("device access", e);
      }
    })();
  }, []);

  // Старт/перезапуск камеры
  TP_R.useEffect(() => {
    if (IS_SLAVE) return;
    (async () => {
      if (camStreamRef.current) camStreamRef.current.getTracks().forEach(t => t.stop());
      try {
        const s = await navigator.mediaDevices.getUserMedia({
          video: camId ? { deviceId: { exact: camId }, width: { ideal: 1080 }, height: { ideal: 1920 } } : { width: { ideal: 1080 }, height: { ideal: 1920 } },
          audio: micId ? { deviceId: { exact: micId } } : true
        });
        camStreamRef.current = s;
        if (videoElRef.current) videoElRef.current.srcObject = s;
      } catch (e) {
        console.error("camera start", e);
      }
    })();
  }, [camId, micId]);

  // QR код для iPhone
  TP_R.useEffect(() => {
    if (IS_SLAVE) return;
    fetch("/api/network/ip").then(r => r.json()).then(({ ip, port }) => {
      const url = `http://${ip}:${port}/#prompter?id=${VID || "default"}&mode=slave`;
      setSlaveLink(url);
      setQrUrl(`https://api.qrserver.com/v1/create-qr-code/?size=240x240&margin=0&data=${encodeURIComponent(url)}`);
    });
  }, [VID]);

  // SYNC: master push, slave pull
  TP_R.useEffect(() => {
    let interval;
    if (IS_SLAVE) {
      interval = setInterval(async () => {
        try {
          const r = await fetch(`/api/teleprompter/state?room=${ROOM}`);
          const data = await r.json();
          if (!data) return;
          if (typeof data.scrollPos === "number") {
            scrollPosRef.current = data.scrollPos;
            if (scrollElRef.current) scrollElRef.current.style.transform = `translateY(${-data.scrollPos}px)`;
          }
          if (typeof data.text === "string" && data.text !== text) setText(data.text);
          if (typeof data.fs === "number") setFontSize(data.fs);
        } catch (e) {}
      }, 80);
    } else {
      interval = setInterval(async () => {
        try {
          await fetch(`/api/teleprompter/state?room=${ROOM}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scrollPos: scrollPosRef.current,
              playing,
              text,
              fs: fontSize,
              versionIdx
            })
          });
        } catch (e) {}
      }, 80);
    }
    return () => clearInterval(interval);
  }, [IS_SLAVE, ROOM, text, fontSize, versionIdx, playing]);

  // Хоткеи
  TP_R.useEffect(() => {
    const onKey = (e) => {
      if (document.activeElement?.tagName === "TEXTAREA" || document.activeElement?.tagName === "INPUT") return;
      if (e.code === "Space") { e.preventDefault(); setPlaying(p => !p); lastFrameRef.current = 0; }
      else if (e.code === "ArrowUp") { e.preventDefault(); setSpeed(s => Math.min(120, s + 5)); }
      else if (e.code === "ArrowDown") { e.preventDefault(); setSpeed(s => Math.max(10, s - 5)); }
      else if (e.code === "KeyR") { e.preventDefault(); toggleRecord(); }
      else if (e.code === "Escape") { e.preventDefault(); setPlaying(false); scrollPosRef.current = 0; if (scrollElRef.current) scrollElRef.current.style.transform = "translateY(0)"; }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // canvas-pipeline для записи
  function buildRecordStream() {
    // размеры canvas фиксируются на момент старта
    let W, H;
    if (aspectRef.current === "1:1") { W = 1080; H = 1080; }
    else if (aspectRef.current === "16:9") { W = 1920; H = 1080; }
    else { W = 1080; H = 1920; }
    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");
    const v = videoElRef.current;

    function draw() {
      if (!v.videoWidth) { recRafRef.current = requestAnimationFrame(draw); return; }
      const vw = v.videoWidth, vh = v.videoHeight;
      // читаем АКТУАЛЬНЫЕ значения зума и пана на каждом кадре
      const z = zoomRef.current || 1;
      const px = panXRef.current || 0;
      const py = panYRef.current || 0;
      const targetAR = W / H;
      const srcAR = vw / vh;
      let sw, sh;
      if (srcAR > targetAR) { sh = vh; sw = sh * targetAR; } else { sw = vw; sh = sw / targetAR; }
      sw /= z; sh /= z;
      const cx = vw / 2 + (vw - sw) * (px / 100);
      const cy = vh / 2 + (vh - sh) * (py / 100);
      let sx = cx - sw / 2, sy = cy - sh / 2;
      sx = Math.max(0, Math.min(vw - sw, sx));
      sy = Math.max(0, Math.min(vh - sh, sy));
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, W, H);
      ctx.save();
      ctx.translate(W, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(v, sx, sy, sw, sh, 0, 0, W, H);
      ctx.restore();
      recRafRef.current = requestAnimationFrame(draw);
    }
    draw();
    const stream = canvas.captureStream(30);
    camStreamRef.current.getAudioTracks().forEach(t => stream.addTrack(t));
    return stream;
  }

  function toggleRecord() {
    if (recorderRef.current && recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    } else {
      if (!camStreamRef.current) { alert("Камера не подключена"); return; }
      chunksRef.current = [];
      const mime = detectMime();
      const stream = buildRecordStream();
      const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8_000_000 });
      recorderRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        if (recRafRef.current) cancelAnimationFrame(recRafRef.current);
        const ext = mime.includes("mp4") ? "mp4" : "webm";
        const blob = new Blob(chunksRef.current, { type: mime });
        const url = URL.createObjectURL(blob);
        const dur = Math.floor((Date.now() - recStartRef.current) / 1000);
        const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        const name = `${VID || "take"}_${ts}.${ext}`;
        // локальный record для мгновенного UI
        setTakes(t => [{ url, name, dur, ext, blob, local: true }, ...t]);
        setRecordingState({ recording: false, dur: 0, fmt: fmtMime(mime) });
        setPlaying(false);
        scrollPosRef.current = 0;
        if (scrollElRef.current) scrollElRef.current.style.transform = "translateY(0)";
        // автоупгрейд: сохраняем на сервер чтобы пережил перезагрузку
        if (VID) {
          try {
            const form = new FormData();
            form.append("video", blob, name);
            form.append("script", text);
            form.append("video_id", VID);
            form.append("version_idx", String(versionIdx));
            form.append("duration", String(dur));
            const r = await fetch("/api/teleprompter/takes", { method: "POST", body: form });
            const j = await r.json();
            if (j.ok && j.take) {
              setTakes(t => t.map(x => x.name === name ? {...x, id: j.take.id, persisted: true, server_url: `/api/teleprompter/takes/${j.take.id}/video`} : x));
            }
          } catch (e) { console.error("save take", e); }
        }
      };
      rec.start();
      recStartRef.current = Date.now();
      setRecordingState({ recording: true, dur: 0, fmt: fmtMime(mime) });
      setPlaying(true);
      lastFrameRef.current = 0;
    }
  }

  // таймер записи
  TP_R.useEffect(() => {
    if (!recordingState.recording) return;
    const t = setInterval(() => {
      setRecordingState(s => ({ ...s, dur: Math.floor((Date.now() - recStartRef.current) / 1000) }));
    }, 200);
    return () => clearInterval(t);
  }, [recordingState.recording]);

  // === slave UI ===
  if (IS_SLAVE) {
    return (
      <div style={{ background: "#000", position: "fixed", inset: 0, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 30px", overflow: "hidden" }}>
        <div style={{ position: "fixed", top: 10, left: 10, background: "rgba(0,0,0,.6)", padding: "6px 10px", borderRadius: 6, fontSize: 11 }}>📺 SLAVE · {VID}</div>
        <div style={{ maxWidth: 600, width: "100%", height: "100%", overflow: "hidden", position: "relative" }}>
          <div ref={scrollElRef} style={{
            position: "absolute", top: "50%", left: 0, right: 0,
            fontSize: 64, lineHeight: 1.5, fontWeight: 600, color: "#fff",
            textAlign: "center", whiteSpace: "pre-wrap",
            textShadow: "0 2px 12px rgba(0,0,0,.95)", willChange: "transform"
          }}>{text}</div>
        </div>
      </div>
    );
  }

  // === master UI ===
  const recMime = detectMime();

  return (
    <div style={{ position: "fixed", inset: 0, top: 70, display: "grid", gridTemplateColumns: "300px 1fr", background: "var(--bg)", overflow: "hidden" }}>
      {/* Sidebar */}
      <aside style={{ background: "var(--bg-2)", borderRight: "1px solid var(--line)", padding: 16, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, color: "var(--ink)" }}>
        <h2 style={{ margin: 0, fontSize: 13, fontWeight: 700, fontFamily: "Unbounded, sans-serif", lineHeight: 1.3, color: "var(--ink)" }}>{video?.title || "Без шортса"}</h2>
        <div style={{ color: "var(--muted)", fontSize: 11 }}>
          {video && <>👁 {fmtViewsCompact(video.view_count)} · <a href={video.url} target="_blank" rel="noopener" style={{ color: "var(--lime-deep)", textDecoration: "none", fontWeight: 600 }}>▶ оригинал</a></>}
        </div>

        {versions.length > 0 && (
          <>
            <label style={tpLabel}>Версия рерайта</label>
            <select value={versionIdx} onChange={e => setVersionIdx(parseInt(e.target.value))} style={tpInput}>
              {versions.map((r, i) => <option key={i} value={i}>{r.product} ({r.score}/5)</option>)}
            </select>
          </>
        )}

        <label style={tpLabel}>Текст</label>
        <textarea value={text} onChange={e => setText(e.target.value)} style={{ ...tpInput, minHeight: 120, fontSize: 11, lineHeight: 1.5, resize: "vertical" }} />

        <label style={tpLabel}>Скорость: {speed} px/сек</label>
        <input type="range" min={10} max={120} value={speed} onChange={e => setSpeed(parseInt(e.target.value))} />

        <label style={tpLabel}>Шрифт: {fontSize}px</label>
        <input type="range" min={20} max={72} value={fontSize} onChange={e => setFontSize(parseInt(e.target.value))} />

        <label style={tpLabel}>Прозрачность: {opacity}%</label>
        <input type="range" min={30} max={100} value={opacity} onChange={e => setOpacity(parseInt(e.target.value))} />

        <label style={tpLabel}>Где камера / куда смотришь</label>
        <div style={{ display: "flex", gap: 4 }}>
          <button onClick={() => { setDirection("up"); scrollPosRef.current = 0; }}
            style={tpBtn(direction === "up")}>📷 Камера по центру</button>
          <button onClick={() => { setDirection("down"); scrollPosRef.current = 0; }}
            style={tpBtn(direction === "down")}>🔄 Камера сверху (перевёрнут)</button>
        </div>


        <label style={tpLabel}>Камера</label>
        <select value={camId} onChange={e => setCamId(e.target.value)} style={tpInput}>
          {cams.map(c => <option key={c.deviceId} value={c.deviceId}>{c.label || "Камера"}</option>)}
        </select>

        <label style={tpLabel}>Микрофон</label>
        <select value={micId} onChange={e => setMicId(e.target.value)} style={tpInput}>
          {mics.map(m => <option key={m.deviceId} value={m.deviceId}>{m.label || "Микрофон"}</option>)}
        </select>

        <label style={tpLabel}>Формат записи</label>
        <div style={{ display: "flex", gap: 4 }}>
          {["9:16", "1:1", "16:9"].map(a => (
            <button key={a} onClick={() => setAspect(a)} style={tpBtn(aspect === a)}>{a}</button>
          ))}
        </div>

        <label style={tpLabel}>Зум: {zoom.toFixed(1)}×</label>
        <input type="range" min={100} max={400} value={Math.round(zoom * 100)} onChange={e => setZoom(parseInt(e.target.value) / 100)} />
        <div style={{ display: "flex", gap: 4 }}>
          {[1, 1.5, 2, 3].map(z => (
            <button key={z} onClick={() => setZoom(z)} style={tpBtn(zoom === z)}>{z}×</button>
          ))}
        </div>

        <label style={tpLabel}>Кадр</label>
        <div style={{ display: "flex", gap: 4 }}>
          <button onClick={() => { setPanY(p => Math.max(-50, p - 8)); }} style={tpBtn()}>↑</button>
          <button onClick={() => { setPanX(p => Math.max(-50, p - 8)); }} style={tpBtn()}>←</button>
          <button onClick={() => { setPanX(0); setPanY(0); }} style={tpBtn()}>⊙</button>
          <button onClick={() => { setPanX(p => Math.min(50, p + 8)); }} style={tpBtn()}>→</button>
          <button onClick={() => { setPanY(p => Math.min(50, p + 8)); }} style={tpBtn()}>↓</button>
        </div>

        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          <button onClick={() => { setPlaying(p => !p); lastFrameRef.current = 0; }} style={{ ...tpBtn(), flex: 1, padding: "9px 10px" }}>{playing ? "⏸ Пауза" : "▶ Старт"}</button>
          <button onClick={() => { setPlaying(false); scrollPosRef.current = 0; if (scrollElRef.current) scrollElRef.current.style.transform = "translateY(0)"; }} style={{ ...tpBtn(), flex: 1, padding: "9px 10px" }}>⟲</button>
        </div>

        <button onClick={toggleRecord} style={{
          padding: "10px 14px", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: "pointer",
          background: recordingState.recording ? "#e63946" : "var(--lime)",
          color: recordingState.recording ? "#fff" : "#11140F",
          marginTop: 4, fontFamily: "Inter, sans-serif"
        }}>
          {recordingState.recording ? `■ Стоп (${recordingState.dur}s)` : "● Записать"}
        </button>

        <label style={tpLabel}>Дубли · <span style={{ textTransform: "none", color: "var(--muted)", fontWeight: 400 }}>{fmtMime(recMime)}</span></label>
        {takes.length === 0 ? (
          <div style={{ color: "var(--muted)", fontSize: 11, padding: 4 }}>Нет дублей</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {takes.map((t, i) => (
              <div key={t.id || t.name || i} style={{ background: "var(--bg-3)", border: "1px solid var(--line)", padding: "8px 10px", borderRadius: 6, fontSize: 11, display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                  <a href={t.server_url || t.url} download={t.name} style={{ color: "var(--lime-deep)", textDecoration: "none", fontWeight: 600 }}>
                    ⬇ Take {takes.length - i} ({t.dur}s) {t.persisted ? "💾" : "📱"}
                  </a>
                  <button
                    title="Удалить дубль"
                    onClick={async () => {
                      if (!confirm("Удалить этот дубль?")) return;
                      if (t.id) {
                        try { await fetch(`/api/teleprompter/takes/${t.id}`, { method: "DELETE" }); } catch (e) {}
                      }
                      if (t.url && t.url.startsWith("blob:")) URL.revokeObjectURL(t.url);
                      setTakes(arr => arr.filter((_, idx) => idx !== i));
                    }}
                    style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--muted)", width: 22, height: 22, borderRadius: 4, fontSize: 12, cursor: "pointer", lineHeight: 1, padding: 0 }}>×</button>
                </div>
                <button
                  onClick={() => window.__OPEN_PROCESS?.(t, text)}
                  style={{ background: "var(--lime)", color: "#11140F", border: "none", padding: "5px 10px", borderRadius: 4, fontSize: 10, fontWeight: 700, cursor: "pointer", fontFamily: "Inter, sans-serif" }}>
                  ⚙ Обработать через shorts-cutter
                </button>
              </div>
            ))}
          </div>
        )}
        {qrUrl && (
          <>
            <label style={tpLabel}>iPhone-слейв</label>
            <div style={{ background: "#fff", padding: 10, borderRadius: 8, textAlign: "center", border: "1px solid var(--line)", boxShadow: "0 2px 8px rgba(17,20,15,.08)" }}>
              <img src={qrUrl} style={{ width: "100%", maxWidth: 200, display: "block", margin: "0 auto" }} />
              <div style={{ fontSize: 9, color: "#000", wordBreak: "break-all", marginTop: 6, fontFamily: "ui-monospace, monospace" }}>{slaveLink}</div>
            </div>
          </>
        )}
      </aside>

      {/* Stage */}
      <main style={{ position: "relative", background: "#000", overflow: "hidden" }}>
        <div ref={camWrapRef} style={{
          position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          width: 540, height: 960, borderRadius: 16, overflow: "hidden", border: "2px solid rgba(255,255,255,.15)",
          boxShadow: recordingState.recording ? "0 0 60px rgba(230,57,70,.5)" : "0 30px 60px rgba(0,0,0,.5)",
          background: "#0a0a0a", zIndex: 2
        }}>
          <video ref={videoElRef} autoPlay muted playsInline style={{
            width: "100%", height: "100%", objectFit: "cover",
            transform: `translate(${panX}%, ${panY}%) scale(${zoom}) scaleX(-1)`,
            transformOrigin: "center center", transition: "transform .1s linear"
          }} />
          {recordingState.recording && (
            <>
              <span style={{ position: "absolute", top: 8, left: 8, background: "rgba(0,0,0,.75)", padding: "3px 8px", borderRadius: 4, fontSize: 10, color: "#fff" }}>● REC</span>
              <span style={{ position: "absolute", top: 8, right: 8, background: "rgba(0,0,0,.75)", padding: "3px 8px", borderRadius: 4, fontSize: 10, color: "#fff", fontFamily: "ui-monospace, monospace" }}>
                {String(Math.floor(recordingState.dur / 60)).padStart(2, "0")}:{String(recordingState.dur % 60).padStart(2, "0")}
              </span>
            </>
          )}
        </div>

        {/* Текст поверх камеры */}
        <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: 480, height: 960, overflow: "hidden", zIndex: 1000, pointerEvents: "none", opacity: opacity / 100 }}>
          <div ref={scrollElRef} style={{
            position: "absolute",
            // up: текст в центре кадра, едет вверх
            // down: текст перевёрнут вертикально, стартует от низа кадра (т.к. перевёрнут — это его «начало»)
            top: direction === "down" ? "auto" : "50%",
            bottom: direction === "down" ? "50%" : "auto",
            left: 0, right: 0,
            fontSize, lineHeight: 1.5, fontWeight: 600, color: "#fff", textAlign: "center", whiteSpace: "pre-wrap",
            textShadow: "0 2px 6px rgba(0,0,0,.95), 0 0 14px rgba(0,0,0,.7)", willChange: "transform",
            transformOrigin: direction === "down" ? "center bottom" : "center center",
          }}>{text}</div>
        </div>
      </main>

      <ProcessModal />
    </div>
  );
}

// === ProcessModal: обработка через shorts-cutter + публикация ===
function ProcessModal() {
  const [open, setOpen] = TP_R.useState(false);
  const [take, setTake] = TP_R.useState(null);
  const [script, setScript] = TP_R.useState("");
  const [opts, setOpts] = TP_R.useState({
    auto_cut: true, subtitles: true,
    brand: "excella", apply_brand: true, cta_key: "",
    apply_watermark: true, apply_face: true, apply_bottom_strip: true,
    effects: false, effects_zoom: true, effects_emoji: true, effects_hook: false, effects_sfx: false,
    subtitle_template: "block"
  });
  const SUB_TEMPLATES = ["block", "karaoke", "minimal", "neon", "telegram", "big_white", "submagic", "captions", "podcast_pro", "beast", "karaoke_fill", "highlight_box", "bubble", "chroma"];
  const POSITIONS = ["top-left","top-center","top-right","center-left","center","center-right","bottom-left","bottom-center","bottom-right"];
  const [brandList, setBrandList] = TP_R.useState([]);
  const [currentBrand, setCurrentBrand] = TP_R.useState(null);
  const [brandDirty, setBrandDirty] = TP_R.useState(false);
  const [showBrandEditor, setShowBrandEditor] = TP_R.useState(false);

  TP_R.useEffect(() => {
    if (!open) return;
    fetch("/brands").then(r => r.json()).then(setBrandList);
  }, [open]);

  // подгружаем полные данные выбранного бренда
  TP_R.useEffect(() => {
    if (!open || !opts.brand) return;
    fetch(`/brands/${opts.brand}`).then(r => r.json()).then(b => { setCurrentBrand(b); setBrandDirty(false); });
  }, [open, opts.brand]);

  const updateBrandField = (path, value) => {
    setCurrentBrand(b => {
      if (!b) return b;
      const next = JSON.parse(JSON.stringify(b));
      const keys = path.split(".");
      let cur = next;
      for (let i = 0; i < keys.length - 1; i++) {
        if (cur[keys[i]] == null) cur[keys[i]] = {};
        cur = cur[keys[i]];
      }
      cur[keys[keys.length - 1]] = value;
      return next;
    });
    setBrandDirty(true);
  };

  const saveBrand = async () => {
    if (!currentBrand) return;
    const patch = {
      lead_url: currentBrand.lead_url,
      niche: currentBrand.niche,
      watermark_position: currentBrand.watermark_position,
      watermark_opacity: currentBrand.watermark_opacity,
      watermark_scale: currentBrand.watermark_scale,
      face_overlay_position: currentBrand.face_overlay_position,
      face_overlay_scale: currentBrand.face_overlay_scale,
      face_overlay_circle: currentBrand.face_overlay_circle,
      bottom_strip: currentBrand.bottom_strip,
      cta_default: currentBrand.cta_default,
    };
    const r = await fetch(`/brands/${currentBrand.name}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (r.ok) {
      setBrandDirty(false);
      fetch("/brands").then(r => r.json()).then(setBrandList);
    } else {
      alert("Не удалось сохранить бренд: " + r.status);
    }
  };

  const createBrandCopy = async () => {
    const name = prompt("Имя нового бренда (латиница, цифры, дефис, _; начинается с буквы):");
    if (!name) return;
    const r = await fetch("/brands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, copy_from: currentBrand?.name }),
    });
    if (r.ok) {
      const created = await r.json();
      setOpts(o => ({...o, brand: created.name}));
      fetch("/brands").then(r => r.json()).then(setBrandList);
    } else {
      const e = await r.text();
      alert("Ошибка: " + e);
    }
  };
  const [jobId, setJobId] = TP_R.useState(null);
  const [job, setJob] = TP_R.useState(null);
  const [publishing, setPublishing] = TP_R.useState(false);
  const [publishResult, setPublishResult] = TP_R.useState(null);
  const [publishStatus, setPublishStatus] = TP_R.useState(null);
  const [title, setTitle] = TP_R.useState("");
  const [description, setDescription] = TP_R.useState("");
  const [tagsText, setTagsText] = TP_R.useState("shorts business");
  const [privacy, setPrivacy] = TP_R.useState("private");
  const [seoGenerating, setSeoGenerating] = TP_R.useState(false);

  const genSEO = async () => {
    setSeoGenerating(true);
    try {
      const r = await fetch("/api/seo/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script,
          niche: currentBrand?.niche || "",
          brand: opts.brand,
          lead_url: currentBrand?.lead_url || "",
        }),
      });
      const j = await r.json();
      if (j.ok && j.seo) {
        setTitle(j.seo.title || "");
        const desc = (j.seo.description || "") + (j.seo.hashtags?.length ? "\n\n" + j.seo.hashtags.join(" ") : "");
        setDescription(desc);
        setTagsText((j.seo.tags || []).join(" "));
      } else {
        alert("SEO не сгенерировано: " + (j.error || "?"));
      }
    } catch (e) { alert(String(e)); }
    finally { setSeoGenerating(false); }
  };

  TP_R.useEffect(() => {
    window.__OPEN_PROCESS = (t, scriptText) => {
      setTake(t);
      setScript(scriptText || "");
      setJobId(null);
      setJob(null);
      setPublishResult(null);
      setOpen(true);
      // подгружаем YouTube статус
      fetch(`/api/teleprompter/publish/status?brand=${opts.brand}`).then(r => r.json()).then(setPublishStatus);
    };
    return () => { window.__OPEN_PROCESS = null; };
  }, [opts.brand]);

  // polling
  TP_R.useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/teleprompter/jobs/${jobId}`);
        const j = await r.json();
        setJob(j);
        if (j.status === "done" || j.status === "error") return;
      } catch (e) {}
      if (!stop) setTimeout(tick, 800);
    };
    tick();
    return () => { stop = true; };
  }, [jobId]);

  const startProcess = async () => {
    if (!take) return;
    const form = new FormData();
    form.append("video", take.blob || (await fetch(take.url).then(r => r.blob())), take.name);
    form.append("script", script);
    form.append("auto_cut", String(opts.auto_cut));
    form.append("subtitles", String(opts.subtitles));
    form.append("brand", opts.brand);
    form.append("effects", String(opts.effects));
    form.append("subtitle_template", opts.subtitle_template);
    form.append("apply_brand", String(opts.apply_brand));
    form.append("apply_watermark", String(opts.apply_watermark));
    form.append("apply_face", String(opts.apply_face));
    form.append("apply_bottom_strip", String(opts.apply_bottom_strip));
    form.append("cta_key", opts.cta_key);
    form.append("meta_title", title || "");
    form.append("meta_description", description || "");
    form.append("meta_tags", tagsText || "");
    form.append("effects", String(opts.effects));
    form.append("effects_zoom", String(opts.effects_zoom));
    form.append("effects_emoji", String(opts.effects_emoji));
    form.append("effects_hook", String(opts.effects_hook));
    form.append("effects_sfx", String(opts.effects_sfx));
    const r = await fetch("/api/teleprompter/upload", { method: "POST", body: form });
    const j = await r.json();
    if (j.ok) {
      setJobId(j.job_id);
    } else {
      alert(j.error || "Ошибка загрузки");
    }
  };

  const publish = async () => {
    if (!jobId) return;
    setPublishing(true);
    setPublishResult(null);
    try {
      const r = await fetch(`/api/teleprompter/publish/${jobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand: opts.brand,
          title, description,
          tags: tagsText.split(/\s+/).filter(Boolean),
          privacy,
        })
      });
      const j = await r.json();
      setPublishResult(j);
    } catch (e) {
      setPublishResult({ ok: false, error: String(e) });
    } finally {
      setPublishing(false);
    }
  };

  if (!open) return null;

  // рендерим через портал прямо в body, чтобы sticky-header сайта не перекрывал
  return ReactDOM.createPortal(
    <div onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.7)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 999999, padding: 20, backdropFilter: "blur(8px)" }}>
      <div style={{ background: "var(--bg-2)", color: "var(--ink)", width: "100%", maxWidth: 720, maxHeight: "90vh", display: "flex", flexDirection: "column", borderRadius: 16, border: "1px solid var(--line)", boxShadow: "0 40px 100px rgba(0,0,0,.4)", overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0, fontFamily: "Unbounded, sans-serif", fontSize: 16 }}>Обработка дубля</h2>
          <button onClick={() => setOpen(false)} style={{ background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", width: 30, height: 30, borderRadius: 6, cursor: "pointer", fontSize: 16, lineHeight: 1 }}>×</button>
        </div>

        <div style={{ padding: 20, overflowY: "auto", flex: 1 }}>
          {!jobId && (
            <>
              <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 600, marginBottom: 6 }}>Опции</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 14 }}>
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                  <input type="checkbox" checked={opts.auto_cut} onChange={e => setOpts(o => ({...o, auto_cut: e.target.checked}))} />
                  Авто-нарезка <span style={{color:"var(--muted)",fontSize:11}}>— убрать «эээ», паузы, оговорки</span>
                </label>
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                  <input type="checkbox" checked={opts.subtitles} onChange={e => setOpts(o => ({...o, subtitles: e.target.checked}))} />
                  Субтитры по сценарию <span style={{color:"var(--muted)",fontSize:11}}>— без ошибок whisper</span>
                </label>
                {opts.subtitles && (
                  <div style={{ marginLeft: 24, marginTop: 4 }}>
                    <label style={{ fontSize: 11, color: "var(--muted)", display: "block", marginBottom: 4 }}>Шаблон субтитров (shorts-cutter пресет)</label>
                    <select value={opts.subtitle_template}
                      onChange={e => setOpts(o => ({...o, subtitle_template: e.target.value}))}
                      style={{ background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "6px 10px", borderRadius: 6, fontSize: 12, fontFamily: "Inter, sans-serif" }}>
                      {SUB_TEMPLATES.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                )}
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                  <input type="checkbox" checked={opts.apply_brand} onChange={e => setOpts(o => ({...o, apply_brand: e.target.checked}))} />
                  Брендинг <span style={{color:"var(--muted)",fontSize:11}}>— лого, лицо, нижняя полоса, CTA</span>
                </label>
                {opts.apply_brand && (
                  <BrandEditor
                    opts={opts} setOpts={setOpts}
                    brandList={brandList} currentBrand={currentBrand}
                    updateBrandField={updateBrandField}
                    brandDirty={brandDirty}
                    saveBrand={saveBrand} createBrandCopy={createBrandCopy}
                    POSITIONS={POSITIONS}
                    showEditor={showBrandEditor} setShowEditor={setShowBrandEditor}
                  />
                )}
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
                  <input type="checkbox" checked={opts.effects} onChange={e => setOpts(o => ({...o, effects: e.target.checked}))} />
                  Эффекты <span style={{color:"var(--muted)",fontSize:11}}>— LLM-план: zoom + emoji + hook + sfx</span>
                </label>
                {opts.effects && (
                  <div style={{ marginLeft: 24, marginTop: 4, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, background: "var(--bg-3)", border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px" }}>
                    <ToggleRow label="🔍 Zoom на акцентах" checked={opts.effects_zoom} onChange={v => setOpts(o => ({...o, effects_zoom: v}))} />
                    <ToggleRow label="😀 Emoji-оверлеи" checked={opts.effects_emoji} onChange={v => setOpts(o => ({...o, effects_emoji: v}))} />
                    <ToggleRow label="🎯 Hook-текст" checked={opts.effects_hook} onChange={v => setOpts(o => ({...o, effects_hook: v}))} />
                    <ToggleRow label="🔊 SFX (ElevenLabs)" checked={opts.effects_sfx} onChange={v => setOpts(o => ({...o, effects_sfx: v}))} hint="нужен ключ" />
                  </div>
                )}
              </div>

              <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 600, marginBottom: 6 }}>Сценарий (что должно остаться)</div>
              <textarea value={script} onChange={e => setScript(e.target.value)} rows={6}
                style={{ width: "100%", background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "10px 14px", borderRadius: 8, fontSize: 12, fontFamily: "Inter, sans-serif", outline: "none", resize: "vertical", lineHeight: 1.5 }} />

              <button onClick={startProcess}
                style={{ marginTop: 16, background: "var(--lime)", color: "#11140F", border: "none", padding: "11px 22px", borderRadius: 10, fontSize: 14, fontWeight: 700, cursor: "pointer", fontFamily: "Inter, sans-serif" }}>
                ▶ Запустить обработку
              </button>
            </>
          )}

          {jobId && job && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{job.step || "…"}</div>
                <div style={{ fontSize: 12, color: job.status === "error" ? "#e63946" : job.status === "done" ? "var(--lime-deep)" : "var(--muted)" }}>
                  {job.status === "done" ? "✓ Готово" : job.status === "error" ? "✗ Ошибка" : `${job.progress || 0}%`}
                </div>
              </div>
              <div style={{ height: 6, background: "var(--bg)", borderRadius: 3, overflow: "hidden", marginBottom: 14 }}>
                <div style={{ width: `${job.progress || 0}%`, height: "100%", background: job.status === "error" ? "#e63946" : "var(--lime)", transition: "width .3s" }}></div>
              </div>

              {job.result && (
                <>
                  <video src={`/api/teleprompter/jobs/${jobId}/preview`} controls
                    style={{ width: "100%", maxHeight: 480, background: "#000", borderRadius: 8, marginBottom: 14 }} />
                  <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 12 }}>
                    Покрытие сценария: <b style={{color:"var(--ink)"}}>{Math.round(job.result.coverage*100)}%</b> ·
                    Сегментов: <b style={{color:"var(--ink)"}}>{job.result.ranges.length}</b> ·
                    Размер: <b style={{color:"var(--ink)"}}>{job.result.size_kb} KB</b>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 600 }}>
                      Публикация на YouTube
                      {publishStatus && (
                        <span style={{ marginLeft: 8, color: publishStatus.connected ? "var(--lime-deep)" : "#e63946" }}>
                          {publishStatus.connected ? `✓ ${publishStatus.channel_title}` : "✗ не подключён"}
                        </span>
                      )}
                    </div>
                    <button onClick={genSEO} disabled={seoGenerating || !script}
                      style={{ background: "var(--bg-3)", color: "var(--ink)", border: "1px solid var(--lime)", padding: "5px 12px", borderRadius: 6, fontSize: 11, cursor: (seoGenerating || !script) ? "not-allowed" : "pointer", fontWeight: 600, fontFamily: "Inter, sans-serif" }}>
                      {seoGenerating ? "⏳ Генерация…" : "✨ Сгенерировать SEO"}
                    </button>
                  </div>
                  <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Заголовок шортса"
                    style={{ width: "100%", background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "8px 12px", borderRadius: 6, fontSize: 12, marginBottom: 8, fontFamily: "Inter, sans-serif" }} />
                  <textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="Описание" rows={3}
                    style={{ width: "100%", background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "8px 12px", borderRadius: 6, fontSize: 12, marginBottom: 8, fontFamily: "Inter, sans-serif" }} />
                  <input value={tagsText} onChange={e => setTagsText(e.target.value)} placeholder="Теги через пробел"
                    style={{ width: "100%", background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "8px 12px", borderRadius: 6, fontSize: 12, marginBottom: 8, fontFamily: "Inter, sans-serif" }} />
                  <select value={privacy} onChange={e => setPrivacy(e.target.value)}
                    style={{ background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "8px 12px", borderRadius: 6, fontSize: 12, marginRight: 8, fontFamily: "Inter, sans-serif" }}>
                    <option value="private">Приватно</option>
                    <option value="unlisted">По ссылке</option>
                    <option value="public">Публично</option>
                  </select>
                  <button onClick={publish} disabled={!publishStatus?.connected || publishing}
                    style={{ background: "var(--lime)", color: "#11140F", border: "none", padding: "8px 16px", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: (publishStatus?.connected && !publishing) ? "pointer" : "not-allowed", opacity: (publishStatus?.connected && !publishing) ? 1 : .5, fontFamily: "Inter, sans-serif" }}>
                    {publishing ? "Загрузка…" : "🎬 Опубликовать"}
                  </button>

                  {publishResult && (
                    <div style={{ marginTop: 10, padding: 10, background: publishResult.ok ? "var(--lime-soft)" : "#fef0ef", border: "1px solid " + (publishResult.ok ? "var(--lime)" : "#e63946"), borderRadius: 6, fontSize: 12, color: "#11140F" }}>
                      {publishResult.ok ? (
                        <>✓ Загружено · <a href={publishResult.url} target="_blank" style={{color:"var(--lime-deep)",fontWeight:700}}>{publishResult.url}</a></>
                      ) : (
                        <>✗ {publishResult.error}</>
                      )}
                    </div>
                  )}
                </>
              )}

              <details style={{ marginTop: 12 }}>
                <summary style={{ cursor: "pointer", fontSize: 11, color: "var(--muted)" }}>Лог обработки</summary>
                <pre style={{ fontSize: 10, color: "var(--muted)", maxHeight: 240, overflow: "auto", fontFamily: "ui-monospace, monospace", margin: "6px 0 0", whiteSpace: "pre-wrap" }}>
                  {(job.log || []).slice(-30).join("\n")}
                </pre>
              </details>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

// === BrandEditor: настройка элементов бренда с тогглами вкл/выкл + сохранением ===
function BrandEditor({ opts, setOpts, brandList, currentBrand, updateBrandField, brandDirty, saveBrand, createBrandCopy, POSITIONS, showEditor, setShowEditor }) {
  return (
    <div style={{ marginLeft: 24, marginTop: 4, display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ fontSize: 11, color: "var(--muted)" }}>Бренд</label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {(brandList || []).map(b => (
          <button key={b.name} onClick={() => setOpts(o => ({...o, brand: b.name, cta_key: ""}))}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "6px 10px", borderRadius: 8,
              background: opts.brand === b.name ? "var(--lime)" : "var(--bg-3)",
              color: opts.brand === b.name ? "#11140F" : "var(--ink)",
              border: "1px solid " + (opts.brand === b.name ? "var(--lime)" : "var(--line)"),
              cursor: "pointer", fontSize: 12, fontWeight: opts.brand === b.name ? 700 : 500,
              fontFamily: "Inter, sans-serif"
            }}>
            {b.watermark_url && <img src={b.watermark_url} style={{ height: 16, maxWidth: 50, objectFit: "contain" }} />}
            {b.name}
          </button>
        ))}
        <button onClick={createBrandCopy}
          style={{ padding: "6px 10px", borderRadius: 8, background: "var(--bg-3)", border: "1px dashed var(--line)", color: "var(--muted)", fontSize: 12, cursor: "pointer", fontFamily: "Inter, sans-serif" }}>
          + новый
        </button>
      </div>

      {/* Тогглы элементов */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, marginTop: 8, background: "var(--bg-3)", border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px" }}>
        <ToggleRow label="🖼 Логотип" checked={opts.apply_watermark} onChange={v => setOpts(o => ({...o, apply_watermark: v}))} hint={currentBrand?.watermark_path ? "" : "Не загружен"} />
        <ToggleRow label="👤 Лицо" checked={opts.apply_face} onChange={v => setOpts(o => ({...o, apply_face: v}))} hint={currentBrand?.face_overlay_path ? "" : "Не загружено"} />
        <ToggleRow label="🎬 Нижняя полоса" checked={opts.apply_bottom_strip} onChange={v => setOpts(o => ({...o, apply_bottom_strip: v}))} hint={currentBrand?.bottom_strip ? "" : "Нет"} />
        <ToggleRow label="📢 CTA в конце" checked={!!opts.cta_key} onChange={v => setOpts(o => ({...o, cta_key: v ? (currentBrand?.cta_default || "demo") : ""}))} hint={opts.cta_key || "off"} />
      </div>

      {opts.cta_key && currentBrand?.cta_presets && (
        <div style={{ marginTop: 4 }}>
          <label style={{ fontSize: 10, color: "var(--muted)", display: "block", marginBottom: 4 }}>CTA-пресет</label>
          <select value={opts.cta_key} onChange={e => setOpts(o => ({...o, cta_key: e.target.value}))}
            style={{ background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "6px 10px", borderRadius: 6, fontSize: 12, fontFamily: "Inter, sans-serif", width: "100%" }}>
            {Object.keys(currentBrand.cta_presets).map(k => <option key={k} value={k}>{k} · {currentBrand.cta_presets[k].text || "(пусто)"}</option>)}
          </select>
        </div>
      )}

      {/* Превью текущих ассетов */}
      {currentBrand && (
        <div style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 10px", background: "var(--bg-3)", border: "1px solid var(--line)", borderRadius: 6, marginTop: 4 }}>
          {currentBrand.watermark_path && opts.apply_watermark && (
            <div style={{ textAlign: "center", opacity: opts.apply_watermark ? 1 : .3 }}>
              <div style={{ fontSize: 9, color: "var(--muted)" }}>Лого</div>
              <img src={`/brand-assets/${currentBrand.watermark_path.split("/").pop()}`} style={{ height: 28, maxWidth: 80, objectFit: "contain" }} />
            </div>
          )}
          {currentBrand.face_overlay_path && opts.apply_face && (
            <div style={{ textAlign: "center", opacity: opts.apply_face ? 1 : .3 }}>
              <div style={{ fontSize: 9, color: "var(--muted)" }}>Лицо</div>
              <img src={`/brand-assets/${currentBrand.face_overlay_path.split("/").pop()}`} style={{ height: 36, maxWidth: 36, objectFit: "contain", borderRadius: currentBrand.face_overlay_circle ? "50%" : 4 }} />
            </div>
          )}
          {currentBrand.bottom_strip && opts.apply_bottom_strip && (
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, color: "var(--muted)" }}>Нижняя полоса</div>
              <div style={{ fontSize: 12, fontWeight: 600, padding: "2px 6px", background: currentBrand.bottom_strip.bg_color, color: currentBrand.bottom_strip.color, borderRadius: 3, display: "inline-block" }}>{currentBrand.bottom_strip.text}</div>
            </div>
          )}
        </div>
      )}

      {/* Кнопка редактора */}
      <button onClick={() => setShowEditor(!showEditor)}
        style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--ink)", padding: "6px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer", marginTop: 4, fontFamily: "Inter, sans-serif" }}>
        {showEditor ? "▾ Скрыть редактор бренда" : "▸ Редактировать бренд"}
      </button>

      {showEditor && currentBrand && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, background: "var(--bg-3)", border: "1px solid var(--line)", borderRadius: 8, padding: "10px 12px", marginTop: 4 }}>
          <SectionTitle>🖼 Логотип (watermark)</SectionTitle>
          <Row label="Позиция">
            <select value={currentBrand.watermark_position || "top-right"} onChange={e => updateBrandField("watermark_position", e.target.value)} style={selectS}>
              {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </Row>
          <Row label={`Прозрачность: ${Math.round((currentBrand.watermark_opacity ?? 0.7) * 100)}%`}>
            <input type="range" min={0} max={1} step={0.05} value={currentBrand.watermark_opacity ?? 0.7}
              onChange={e => updateBrandField("watermark_opacity", parseFloat(e.target.value))} style={{ width: "100%" }} />
          </Row>
          <Row label={`Размер: ${Math.round((currentBrand.watermark_scale ?? 0.1) * 100)}%`}>
            <input type="range" min={0.04} max={0.3} step={0.01} value={currentBrand.watermark_scale ?? 0.1}
              onChange={e => updateBrandField("watermark_scale", parseFloat(e.target.value))} style={{ width: "100%" }} />
          </Row>
          <UploadAsset name={currentBrand.name} type="watermark" hasFile={!!currentBrand.watermark_path} />

          <SectionTitle>👤 Лицо в углу (face overlay)</SectionTitle>
          <Row label="Позиция">
            <select value={currentBrand.face_overlay_position || "bottom-left"} onChange={e => updateBrandField("face_overlay_position", e.target.value)} style={selectS}>
              {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </Row>
          <Row label={`Размер: ${Math.round((currentBrand.face_overlay_scale ?? 0.22) * 100)}%`}>
            <input type="range" min={0.1} max={0.5} step={0.02} value={currentBrand.face_overlay_scale ?? 0.22}
              onChange={e => updateBrandField("face_overlay_scale", parseFloat(e.target.value))} style={{ width: "100%" }} />
          </Row>
          <Row label="Форма">
            <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
              <input type="checkbox" checked={!!currentBrand.face_overlay_circle}
                onChange={e => updateBrandField("face_overlay_circle", e.target.checked)} />
              Круглая
            </label>
          </Row>
          <UploadAsset name={currentBrand.name} type="face-overlay" hasFile={!!currentBrand.face_overlay_path} />

          {currentBrand.bottom_strip && (
            <>
              <SectionTitle>🎬 Нижняя полоса</SectionTitle>
              <Row label="Текст">
                <input value={currentBrand.bottom_strip.text || ""} onChange={e => updateBrandField("bottom_strip.text", e.target.value)} style={inputS} />
              </Row>
              <Row label="Цвет текста">
                <input type="color" value={currentBrand.bottom_strip.color || "#ffffff"} onChange={e => updateBrandField("bottom_strip.color", e.target.value)} style={{ width: 48, height: 28, border: "none", background: "transparent", cursor: "pointer" }} />
              </Row>
              <Row label="Фон">
                <input type="color" value={currentBrand.bottom_strip.bg_color || "#1e1b4b"} onChange={e => updateBrandField("bottom_strip.bg_color", e.target.value)} style={{ width: 48, height: 28, border: "none", background: "transparent", cursor: "pointer" }} />
              </Row>
              <Row label={`Прозрачность: ${Math.round((currentBrand.bottom_strip.opacity ?? 0.85) * 100)}%`}>
                <input type="range" min={0} max={1} step={0.05} value={currentBrand.bottom_strip.opacity ?? 0.85}
                  onChange={e => updateBrandField("bottom_strip.opacity", parseFloat(e.target.value))} style={{ width: "100%" }} />
              </Row>
              <Row label={`Высота: ${currentBrand.bottom_strip.height || 80}px`}>
                <input type="range" min={40} max={300} step={4} value={currentBrand.bottom_strip.height || 80}
                  onChange={e => updateBrandField("bottom_strip.height", parseInt(e.target.value))} style={{ width: "100%" }} />
              </Row>
            </>
          )}

          {/* Сохранение */}
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <button onClick={saveBrand} disabled={!brandDirty}
              style={{ flex: 1, background: brandDirty ? "var(--lime)" : "var(--bg)", color: brandDirty ? "#11140F" : "var(--muted)", border: "1px solid " + (brandDirty ? "var(--lime)" : "var(--line)"), padding: "8px 12px", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: brandDirty ? "pointer" : "not-allowed", fontFamily: "Inter, sans-serif" }}>
              {brandDirty ? "💾 Сохранить изменения" : "Нет изменений"}
            </button>
            <button onClick={createBrandCopy}
              style={{ background: "var(--bg)", color: "var(--ink)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: 6, fontSize: 12, cursor: "pointer", fontFamily: "Inter, sans-serif" }}>
              🆕 Как новый
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ToggleRow({ label, checked, onChange, hint }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer", color: "var(--ink)" }}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      {label}
      {hint && <span style={{ color: "var(--muted)", fontSize: 10, marginLeft: "auto" }}>{hint}</span>}
    </label>
  );
}
function SectionTitle({ children }) {
  return <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 700, marginTop: 6, marginBottom: 2 }}>{children}</div>;
}
function Row({ label, children }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "130px 1fr", gap: 8, alignItems: "center" }}>
      <div style={{ fontSize: 11, color: "var(--muted)" }}>{label}</div>
      <div>{children}</div>
    </div>
  );
}
const selectS = { background: "var(--bg-2)", border: "1px solid var(--line)", color: "var(--ink)", padding: "5px 8px", borderRadius: 4, fontSize: 12, fontFamily: "Inter, sans-serif", width: "100%" };
const inputS = { background: "var(--bg-2)", border: "1px solid var(--line)", color: "var(--ink)", padding: "5px 8px", borderRadius: 4, fontSize: 12, fontFamily: "Inter, sans-serif", width: "100%", outline: "none" };

function UploadAsset({ name, type, hasFile }) {
  const fileRef = TP_R.useRef();
  const [uploading, setUploading] = TP_R.useState(false);
  const [status, setStatus] = TP_R.useState("");
  const upload = async (file) => {
    setUploading(true);
    setStatus("");
    try {
      const f = new FormData();
      f.append("file", file);
      const r = await fetch(`/brands/${name}/${type}`, { method: "POST", body: f });
      if (r.ok) { setStatus("✓ Загружено"); setTimeout(() => location.reload(), 800); }
      else { setStatus("✗ " + r.status); }
    } catch (e) { setStatus("✗ " + e.message); }
    finally { setUploading(false); }
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }}
        onChange={e => e.target.files[0] && upload(e.target.files[0])} />
      <button onClick={() => fileRef.current?.click()} disabled={uploading}
        style={{ background: "var(--bg-2)", color: "var(--ink)", border: "1px dashed var(--line)", padding: "5px 10px", borderRadius: 4, fontSize: 11, cursor: "pointer", fontFamily: "Inter, sans-serif" }}>
        {uploading ? "⏳…" : hasFile ? "↻ Заменить файл" : "+ Загрузить файл"}
      </button>
      {status && <span style={{ color: status.startsWith("✓") ? "var(--lime-deep)" : "#e63946" }}>{status}</span>}
    </div>
  );
}


function fmtViewsCompact(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return Math.round(n / 1e3) + "K";
  return String(n);
}

const tpLabel = { fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 600, marginTop: 4, fontFamily: "Inter, sans-serif" };
const tpInput = { width: "100%", background: "var(--bg-3)", border: "1px solid var(--line)", color: "var(--ink)", padding: "7px 10px", borderRadius: 6, fontSize: 12, fontFamily: "Inter, sans-serif", outline: "none" };
function tpBtn(active) {
  return {
    flex: 1, padding: "6px 8px", borderRadius: 6, fontSize: 11, fontFamily: "Inter, sans-serif", cursor: "pointer",
    background: active ? "var(--lime)" : "var(--bg-3)",
    border: "1px solid " + (active ? "var(--lime)" : "var(--line)"),
    color: active ? "#11140F" : "var(--ink)", fontWeight: active ? 700 : 500
  };
}

window.TELEPROMPTER = { TeleprompterScreen };
