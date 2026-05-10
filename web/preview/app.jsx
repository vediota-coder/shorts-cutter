// Main App — реальные данные из backend FastAPI поверх дизайна-прототипа.
// Стратегия совместимости: после успешного fetch'a перезаписываем window.MOCK.X
// форматом, совместимым с hero-cut.jsx / progress-clips.jsx — компоненты ничего
// не знают о настоящем API. Дальше постепенно перейдём на props-driven передачу.

const { useState, useEffect, useMemo, useRef } = React;

const _now = () => new Date().toLocaleTimeString("ru-RU", { hour12: false });

// ── маппинг ответов backend → формат, совместимый с MOCK ───────────────────
function mapSubtitleTemplates(arr) {
  // backend: [{key, name, size, use_highlight, words_per_chunk, chunk_advance}]
  // MOCK:    [{id, emoji, name, kind, words, pt}]
  return (arr || []).map((t) => ({
    id: t.key,
    emoji: "•",
    name: t.name,
    kind: t.use_highlight ? "karaoke" : "block",
    words: t.words_per_chunk || 3,
    pt: t.size || 56,
  }));
}

function mapLLMProviders(payload) {
  // backend: { default, providers: [{name, label, kind, install, auth, configured, models}] }
  // MOCK:    [{id, name, sub, configured, badge}]
  const list = payload?.providers || [];
  return list.map((p) => ({
    id: p.name,
    name: p.label || p.name,
    sub: p.install || p.auth || "",
    configured: !!p.configured,
    // badge: переводим в месте использования (есть t.badgeSubscription / t.badgeApi)
    badge: p.kind === "subscription" ? "subscription" : "API",
    _kind: p.kind === "subscription" ? "subscription" : "api",
    _models: p.models || [],
  }));
}

function mapBrandCTA(brand) {
  // brand: {name, cta_presets:[{key,text,sub_text}], cta_default, bottom_strip_text}
  // MOCK CTA_PRESETS: [{id, title, url}]
  const presets = (brand?.cta_presets || []).map((p) => ({
    id: p.key,
    title: p.text || p.key,
    url: p.sub_text || "",
  }));
  presets.push({ id: "none", title: "— без CTA —", url: "" });
  return presets;
}

function mapJobsToRecent(jobs) {
  // backend: [{id, status, stage, progress, n_clips, title, source_url, error}]
  return (jobs || []).map((j) => ({
    title: j.title || j.source_url || j.id,
    count: j.n_clips || 0,
    _id: j.id,
    _status: j.status,
    _stage: j.stage,
    _error: j.error,
    _progress: j.progress,
  }));
}

function mapClipsFromJob(jobAsdict) {
  // ClipResult от backend: {index, title, start, end, files: {1080p,720p,480p},
  //   slug, sub_template, brand, cta, meta_title, meta_descriptions: {plat: text},
  //   meta_hashtags: {plat: tags}, meta_lead_links: {plat: url}}
  const clips = jobAsdict?.clips || [];
  const POSTER_ROT = ["scene-pink", "scene-emerald", "scene-amber", "scene-violet"];
  // hashtags может быть в формате {plat: [arr]} или {plat: "string"}
  const _firstStr = (obj) => {
    if (!obj || typeof obj !== "object") return "";
    for (const v of Object.values(obj)) {
      if (Array.isArray(v) && v.length) return v.join(" ");
      if (typeof v === "string" && v) return v;
    }
    return "";
  };
  return clips.map((c, i) => {
    const start = Number(c.start || 0);
    const end = Number(c.end || start);
    const dur = Math.max(0, end - start);
    const fmt = (s) => {
      const m = Math.floor(s / 60), ss = Math.floor(s % 60);
      return `${m}:${String(ss).padStart(2, "0")}`;
    };
    const hasTimes = end > 0;
    // backend хранит 1-based index в ClipResult.index. Внутри фронта держим 0-based.
    const idx0 = (c.index != null ? c.index - 1 : i);
    return {
      id: idx0 + 1,
      n: idx0 + 1,
      _jobId: jobAsdict.id,
      _index: idx0,
      _slug: c.slug || "",
      _files: c.files || {},
      _brand: c.brand || jobAsdict.brand || "excella",
      _cta: c.cta || "demo",
      _start: start,
      _end: end,
      effects_applied: c.effects_applied || null,
      publications: c.publications || {},
      title: c.meta_title || c.title || `${(window.I18N[(window.MOCK?.tweaks?.lang) || "ru"]?.clipNumberFallback) || "Клип"} ${i + 1}`,
      range: hasTimes ? `${fmt(start)} – ${fmt(end)}` : "—",
      duration: hasTimes ? `${Math.round(dur)}${(window.I18N[(window.MOCK?.tweaks?.lang) || "ru"]?.secondsAbbr) || "с"}` : "—",
      activeStyle: c.sub_template || "block",
      description: _firstStr(c.meta_descriptions),
      hashtags: _firstStr(c.meta_hashtags),
      poster: POSTER_ROT[i % POSTER_ROT.length],
    };
  });
}

function App() {
  const { Logo, Icon, Toast } = window.UI;
  const { HeroBlock, CutForm } = window.HEROCUT;
  const { ProgressBlock, RecentJobs, ClipCard } = window.PROGRESSCLIPS;
  const { MetricsModal, BrandsModal, SettingsModal } = window.MODALS;

  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "theme": "light",
    "lang": "ru",
    "showRecentJobs": true,
    "compactClips": false
  }/*EDITMODE-END*/;

  const [tweaks, setTweak] = window.useTweaks
    ? window.useTweaks(TWEAK_DEFAULTS)
    : [TWEAK_DEFAULTS, () => {}];

  // ── form state ─────────────────────────────────────────
  const [url, setUrl] = useState("");
  const [file, setFile] = useState("");
  const [fileObj, setFileObj] = useState(null);
  const [maxClips, setMaxClips] = useState(8);
  const [whisperModel, setWhisperModel] = useState("auto");
  const [voiceover, setVoiceover] = useState(false);
  const [voiceoverEngine, setVoiceoverEngine] = useState("library");
  const [voiceoverMode, setVoiceoverMode] = useState("duck");
  const [voiceoverVoice, setVoiceoverVoice] = useState("EXAVITQu4vr4xnSDxMaL");
  const [voiceoverModel, setVoiceoverModel] = useState("eleven_v3");
  const [voiceoverTargetLang, setVoiceoverTargetLang] = useState("ru");
  const [downloadMax, setDownloadMax] = useState("auto");
  const [cookies, setCookies] = useState("none");
  const [outputSize, setOutputSize] = useState("auto");
  const [subtitleStyleId, setSubtitleStyleId] = useState("block");
  const [llmProviderId, setLlmProviderId] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [ctaPresetId, setCtaPresetId] = useState("demo");
  const [brand, setBrand] = useState("excella");
  const [pickerExtra, setPickerExtra] = useState("");

  // ── server state ───────────────────────────────────────
  const [backendInfo, setBackendInfo] = useState(null);
  const [serverReady, setServerReady] = useState(false);
  const [version, setVersion] = useState(0);   // bump чтобы дочерние компоненты re-rendered после window.MOCK обновления
  const [publishStatus, setPublishStatus] = useState({}); // {instagram, vk, youtube} → {connected, ...}

  // ── cutting flow ──────────────────────────────────────
  const [cutting, setCutting] = useState(false);
  const [percent, setPercent] = useState(0);
  const [log, setLog] = useState([]);
  const [showClips, setShowClips] = useState(false);
  const [clips, setClips] = useState([]);
  const [currentJobId, setCurrentJobId] = useState(null);
  const wsCloseRef = useRef(null);

  // ── modals ─────────────────────────────────────────────
  const [metricsOpen, setMetricsOpen] = useState(false);
  const [brandsOpen, setBrandsOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [toast, setToast] = useState("");

  const i18n = window.I18N[tweaks.lang] || window.I18N.ru;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", tweaks.theme);
  }, [tweaks.theme]);

  const showToast = (m) => {
    setToast(m);
    setTimeout(() => setToast(""), 1800);
  };

  // ── загрузка с backend на mount (Фаза 2A) ─────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [be, llm, subs, brands, jobs] = await Promise.all([
          window.API.backend().catch(() => null),
          window.API.llmProviders().catch(() => null),
          window.API.subtitleTemplates().catch(() => null),
          window.API.brands().catch(() => null),
          window.API.jobs(30).catch(() => null),
        ]);
        if (cancelled) return;

        if (be) setBackendInfo(be);

        if (subs?.length) {
          window.MOCK.SUBTITLE_STYLES = mapSubtitleTemplates(subs);
          // если выбранный стиль уже не существует — берём первый из реальных
          const ids = window.MOCK.SUBTITLE_STYLES.map((s) => s.id);
          if (!ids.includes(subtitleStyleId)) {
            setSubtitleStyleId(ids[0] || "block");
          }
        }

        if (llm) {
          window.MOCK.LLM_PROVIDERS = mapLLMProviders(llm);
          if (!llmProviderId && llm.default) {
            setLlmProviderId(llm.default);
            const def = window.MOCK.LLM_PROVIDERS.find((p) => p.id === llm.default);
            if (def && def._models?.length) setLlmModel(def._models[0]);
          }
        }

        if (brands?.length) {
          // активный бренд → его CTA пресеты
          const active = brands.find((b) => b.name === brand) || brands[0];
          if (active) {
            window.MOCK.CTA_PRESETS = mapBrandCTA(active);
            if (active.cta_default) setCtaPresetId(active.cta_default);
            // если выбранный бренд не существует — берём первый реальный
            if (active.name !== brand) setBrand(active.name);
          }
          window.MOCK._BRANDS_LIST = brands;
        }

        if (jobs?.length) {
          window.MOCK.RECENT_JOBS = mapJobsToRecent(jobs);
        }

        setServerReady(true);
        setVersion((v) => v + 1);
      } catch (e) {
        console.warn("Initial load failed, using mock data:", e);
        setServerReady(true);  // даже при ошибке показываем UI с mock'ом
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // если поменяли LLM провайдера — переиграть выбор модели на дефолтную для нового
  useEffect(() => {
    if (!llmProviderId) return;
    const prov = (window.MOCK.LLM_PROVIDERS || []).find((p) => p.id === llmProviderId);
    if (prov?._models?.length && !prov._models.includes(llmModel)) {
      setLlmModel(prov._models[0]);
    }
  }, [llmProviderId]);

  // ── статусы подключения соцсетей для активного бренда ──
  useEffect(() => {
    if (!brand) return;
    let cancelled = false;
    Promise.all([
      window.API.publishStatus("instagram", brand).catch(() => null),
      window.API.publishStatus("vk", brand).catch(() => null),
      window.API.publishStatus("youtube", brand).catch(() => null),
    ]).then(([ig, vk, yt]) => {
      if (cancelled) return;
      setPublishStatus({ instagram: ig || {}, vk: vk || {}, youtube: yt || {} });
    });
    return () => { cancelled = true; };
  }, [brand]);

  // ── запуск нарезки: POST /jobs + WebSocket ─────────────
  const onCut = async () => {
    if (!url && !fileObj) {
      showToast(i18n.needUrlOrFile);
      return;
    }
    setCutting(true);
    setPercent(0);
    setLog([{ t: _now(), msg: i18n.sendingJob }]);
    setShowClips(false);

    try {
      const heightMap = { "auto": 1080, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360 };
      const payload = {
        url: url || undefined,
        file: fileObj || undefined,
        max_clips: maxClips,
        whisper_model: whisperModel,
        sub_template: subtitleStyleId,
        brand,
        cta: ctaPresetId,
        llm_provider: llmProviderId || "",
        llm_model: llmModel || "",
        download_max_height: heightMap[downloadMax] ?? 1080,
        download_cookies_browser: cookies === "none" ? "" : cookies,
        output_size: outputSize === "auto" ? "native" : outputSize,
        voiceover: voiceover ? "true" : "false",
        voiceover_engine: voiceoverEngine,
        voiceover_mode: voiceoverMode,
        voiceover_voice: voiceoverVoice,
        voiceover_model: voiceoverModel,
        voiceover_target_lang: voiceoverTargetLang,
        picker_extra: pickerExtra || "",
      };
      // прогресс загрузки файла (если файл загружается). Если только URL — XHR
      // отстреляет один onprogress на ~0%; показываем строку только для file uploads.
      let lastProgressLine = -1;
      const onUploadProgress = ({ loaded, total, percent }) => {
        if (!fileObj) return;   // только URL — нет смысла показывать
        const mb = (loaded / 1024 / 1024).toFixed(0);
        const mbT = (total / 1024 / 1024).toFixed(0);
        setPercent(Math.round(percent * 0.05));   // upload = 0..5% от общего прогресса
        const line = { t: _now(), msg: `${i18n.uploadingFile} · ${mb}/${mbT} MB · ${percent.toFixed(0)}%` };
        setLog((prev) => {
          if (lastProgressLine >= 0 && lastProgressLine < prev.length) {
            const next = [...prev]; next[lastProgressLine] = line; return next;
          }
          lastProgressLine = prev.length;
          return [...prev, line];
        });
      };
      const r = await window.API.createJob(payload, onUploadProgress);
      const jobId = r.job_id;
      setCurrentJobId(jobId);
      setLog((p) => [...p, {
        t: _now(),
        msg: fileObj ? `${i18n.fileUploaded} ${jobId}, WebSocket…`
                     : `job_id ${jobId}, WebSocket…`,
        ok: true,
      }]);

      // подключаем WS-стрим
      wsCloseRef.current = window.openJobStream(jobId, {
        onMessage: (line) => {
          if (line.progress != null) setPercent(line.progress);
          if (line.msg) {
            const ok = line.stage === "done" || line.msg.startsWith("✓");
            setLog((p) => [...p, { t: _now(), msg: line.msg, ok }]);
          }
          if (line.stage === "done") {
            setPercent(100);
            // дотягиваем полный job чтобы получить clips с metadata
            window.API.job(jobId).then((j) => {
              const realClips = mapClipsFromJob(j);
              if (realClips.length) {
                setClips(realClips);
                setShowClips(true);
              }
            });
          }
          if (line.stage === "error") {
            setLog((p) => [...p, { t: _now(), msg: `${i18n.errorPrefix} ${line.msg}`, ok: false }]);
            setCutting(false);
          }
        },
        onClose: () => {
          setCutting(false);
          // обновим список последних заданий после нарезки
          window.API.jobs(30).then((js) => {
            if (js?.length) {
              window.MOCK.RECENT_JOBS = mapJobsToRecent(js);
              setVersion((v) => v + 1);
            }
          });
        },
        onError: () => {
          setLog((p) => [...p, { t: _now(), msg: i18n.wsConnError, ok: false }]);
        },
      });
    } catch (e) {
      setLog((p) => [...p, { t: _now(), msg: `${i18n.errorPrefix} ${e.message}`, ok: false }]);
      setCutting(false);
    }
  };

  const onCancel = () => {
    if (wsCloseRef.current) wsCloseRef.current();
    wsCloseRef.current = null;
    setCutting(false);
    setPercent(0);
    setLog([]);
    showToast(i18n.cancelled);
  };

  const handleChangeStyle = (id, styleId) => {
    setClips((prev) => prev.map((c) => (c.id === id ? { ...c, activeStyle: styleId } : c)));
  };

  // открыть конкретный job из «Последних заданий» → загрузить и показать его клипы
  const openJob = async (j) => {
    if (!j._id) return;
    try {
      const job = await window.API.job(j._id);
      const realClips = mapClipsFromJob(job);
      setClips(realClips);
      setCurrentJobId(j._id);
      setShowClips(true);
      showToast(`${i18n.jobOpened} ${(j.title || "").slice(0, 30)}…`);
    } catch (e) {
      showToast(`${i18n.jobOpenFail} ${e.message}`);
    }
  };

  return (
    <>
      {/* Header */}
      <header className="app-header glass">
        <div className="logo">
          <Logo size={20}/>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <span className="brand-pill">
            <span style={{ width: 6, height: 6, borderRadius: 99, background: "var(--green)" }}></span>
            {i18n.brandLabel} {brand}
          </span>
          <button
            className="icon-btn"
            title={i18n.tweakTheme}
            onClick={() => setTweak("theme", tweaks.theme === "dark" ? "light" : "dark")}
          >
            <Icon name="moon" size={14}/>
          </button>
          <div className="seg">
            <button className={tweaks.lang === "ru" ? "on" : ""} onClick={() => setTweak("lang", "ru")}>RU</button>
            <button className={tweaks.lang === "en" ? "on" : ""} onClick={() => setTweak("lang", "en")}>EN</button>
          </div>
        </div>
      </header>

      <main className="shell">
        <HeroBlock
          t={i18n}
          backendInfo={backendInfo}
          onOpenMetrics={() => setMetricsOpen(true)}
          onOpenBrands={() => setBrandsOpen(true)}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <div style={{ marginTop: 24 }}>
          <CutForm
            key={`cut-${version}`}  // force re-render когда обновили window.MOCK
            t={i18n}
            lang={tweaks.lang}
            url={url} setUrl={setUrl}
            file={file} setFile={(name, obj) => { setFile(name); setFileObj(obj || null); }}
            maxClips={maxClips} setMaxClips={setMaxClips}
            whisperModel={whisperModel} setWhisperModel={setWhisperModel}
            downloadMax={downloadMax} setDownloadMax={setDownloadMax}
            cookies={cookies} setCookies={setCookies}
            outputSize={outputSize} setOutputSize={setOutputSize}
            subtitleStyleId={subtitleStyleId} setSubtitleStyleId={setSubtitleStyleId}
            voiceover={voiceover} setVoiceover={setVoiceover}
            voiceoverEngine={voiceoverEngine} setVoiceoverEngine={setVoiceoverEngine}
            voiceoverMode={voiceoverMode} setVoiceoverMode={setVoiceoverMode}
            voiceoverVoice={voiceoverVoice} setVoiceoverVoice={setVoiceoverVoice}
            voiceoverModel={voiceoverModel} setVoiceoverModel={setVoiceoverModel}
            voiceoverTargetLang={voiceoverTargetLang} setVoiceoverTargetLang={setVoiceoverTargetLang}
            llmProviderId={llmProviderId} setLlmProviderId={setLlmProviderId}
            llmModel={llmModel} setLlmModel={setLlmModel}
            ctaPresetId={ctaPresetId} setCtaPresetId={setCtaPresetId}
            brand={brand}
            pickerExtra={pickerExtra} setPickerExtra={setPickerExtra}
            onCut={onCut}
            cutting={cutting}
          />
        </div>

        {(cutting || percent > 0) && (
          <div style={{ marginTop: 24 }}>
            <ProgressBlock percent={percent} log={log} onCancel={onCancel}/>
          </div>
        )}

        {showClips && (
          <div style={{ marginTop: 32 }}>
            <div className="section-h">
              <h3>{i18n.readyClips} <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: 16, marginLeft: 8 }}>· {clips.length} {i18n.clipsAbbr}</span></h3>
              <div className="row" style={{ gap: 8 }}>
                <button className="btn btn-ghost"><Icon name="download" size={14}/> {i18n.downloadAll}</button>
                <button className="btn btn-primary"><Icon name="send" size={14}/> {i18n.publishAllVk}</button>
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {clips.map((c) => (
                <ClipCard
                  key={c.id}
                  clip={c}
                  t={i18n}
                  publishStatus={publishStatus}
                  onPublish={async (clip, target) => {
                    if (!clip._jobId) {
                      showToast(`${i18n.mockPrefix} ${target}`);
                      return;
                    }
                    // Body зависит от платформы:
                    const body = target === "youtube" ? { privacy: "public" }
                              : target === "vk"      ? { privacy: "all" }
                              : target === "instagram" ? { share_to_feed: true }
                              : {};
                    try {
                      showToast(`${i18n.publishingTo} ${target}…`);
                      const r = await window.API.publishClip(
                        clip._jobId, clip._index + 1, target, body
                      );
                      // mark clip as published so card обновится
                      setClips((prev) => prev.map((x) => x.id === clip.id ? {
                        ...x,
                        publications: { ...(x.publications || {}), [target]: { url: r?.url, video_id: r?.video_id } },
                      } : x));
                      showToast(`${i18n.publishedTo} ${target}`);
                    } catch (e) { showToast(`${i18n.publishError} ${target}: ${e.message}`); }
                  }}
                  onMetrics={() => setMetricsOpen(true)}
                  onChangeStyle={handleChangeStyle}
                />
              ))}
            </div>
          </div>
        )}

        {tweaks.showRecentJobs && !showClips && !cutting && (
          <RecentJobs key={`recent-${version}`} t={i18n} onClick={openJob}/>
        )}
      </main>

      <MetricsModal open={metricsOpen} onClose={() => setMetricsOpen(false)} t={i18n}/>
      <BrandsModal open={brandsOpen} onClose={() => setBrandsOpen(false)} t={i18n} brand={brand} setBrand={setBrand}/>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} t={i18n}/>

      <Toast msg={toast}/>

      {/* Tweaks panel */}
      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks · ShortsAI">
          <window.TweakSection title={i18n.tweakAppearance}>
            <window.TweakRadio
              label={i18n.tweakTheme}
              value={tweaks.theme}
              options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }]}
              onChange={(v) => setTweak("theme", v)}
            />
            <window.TweakRadio
              label={i18n.tweakLanguage}
              value={tweaks.lang}
              options={[{ value: "ru", label: "RU" }, { value: "en", label: "EN" }]}
              onChange={(v) => setTweak("lang", v)}
            />
          </window.TweakSection>
          <window.TweakSection title={i18n.tweakState}>
            <window.TweakToggle
              label={i18n.tweakShowRecentJobs}
              value={tweaks.showRecentJobs}
              onChange={(v) => setTweak("showRecentJobs", v)}
            />
          </window.TweakSection>
          <window.TweakSection title={i18n.tweakDemo}>
            <window.TweakButton onClick={() => setMetricsOpen(true)}>{i18n.nav.metrics}</window.TweakButton>
            <window.TweakButton onClick={() => setBrandsOpen(true)}>{i18n.nav.brands}</window.TweakButton>
            <window.TweakButton onClick={() => setSettingsOpen(true)}>{i18n.nav.settings}</window.TweakButton>
          </window.TweakSection>
        </window.TweaksPanel>
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
