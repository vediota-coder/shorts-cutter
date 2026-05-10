// Hero + main "cut" form (v2 — concise, advanced collapsed, no emoji)

function HeroBlock({ t, backendInfo, onOpenMetrics, onOpenBrands, onOpenSettings }) {
  const { Icon } = window.UI;
  // если backend сообщил железо — показываем точные данные, иначе fallback
  const eyebrow = backendInfo
    ? `${backendInfo.name || "shorts-cutter"} · ${backendInfo.device || ""} · ${t.backendModelSep} ${backendInfo.model || "auto"}`
    : `shorts-cutter · ${t.detectingHardware}`;
  return (
    <div className="hero">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <span className="hero-eyebrow">
          <span className="dot"></span>
          <span>{eyebrow}</span>
        </span>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button className="btn btn-ghost" onClick={onOpenMetrics}>
            <Icon name="chart" size={13}/> {t.nav.metrics}
          </button>
          <button className="btn btn-ghost" onClick={onOpenBrands}>
            <Icon name="tag" size={13}/> {t.nav.brands}
          </button>
          <button className="btn btn-ghost" onClick={onOpenSettings}>
            <Icon name="settings" size={13}/> {t.nav.settings}
          </button>
        </div>
      </div>

      <h1 className="h-display hero-title">
        {t.heroLine1}<br/>
        {t.heroLine2In} <span className="lime-mark">{t.heroShorts}</span>.
      </h1>

      <p className="hero-sub">
        {t.heroSub}
      </p>
    </div>
  );
}

function CutForm({
  t,
  url, setUrl,
  file, setFile,
  maxClips, setMaxClips,
  whisperModel, setWhisperModel,
  downloadMax, setDownloadMax,
  cookies, setCookies,
  outputSize, setOutputSize,
  subtitleStyleId, setSubtitleStyleId,
  llmProviderId, setLlmProviderId,
  llmModel, setLlmModel,
  ctaPresetId, setCtaPresetId,
  voiceover, setVoiceover,
  voiceoverEngine, setVoiceoverEngine,
  voiceoverMode, setVoiceoverMode,
  voiceoverVoice, setVoiceoverVoice,
  voiceoverModel, setVoiceoverModel,
  voiceoverTargetLang, setVoiceoverTargetLang,
  brand,
  pickerExtra, setPickerExtra,
  onCut,
  cutting,
}) {
  const { Icon } = window.UI;
  const SUBTITLE_STYLES = window.MOCK.SUBTITLE_STYLES;
  const LLM_PROVIDERS = window.MOCK.LLM_PROVIDERS;
  const CTA_PRESETS = window.MOCK.CTA_PRESETS;

  const [dragOver, setDragOver] = React.useState(false);
  const [showAdvanced, setShowAdvanced] = React.useState(false);
  const [showLLM, setShowLLM] = React.useState(false);
  const [showCTA, setShowCTA] = React.useState(false);
  const [showVoiceover, setShowVoiceover] = React.useState(false);
  const [voicesList, setVoicesList] = React.useState(null); // null = не загружено
  const [voicesLoading, setVoicesLoading] = React.useState(false);
  const [voicesFilter, setVoicesFilter] = React.useState({ language: "any", gender: "any", search: "" });
  const previewAudioRef = React.useRef(null);
  const [playingVoiceId, setPlayingVoiceId] = React.useState(null);

  const loadVoices = async () => {
    setVoicesLoading(true);
    try {
      const r = await window.API.elevenlabsVoices();
      setVoicesList(r.voices || []);
    } catch (e) {
      alert(t.voicesLoadFailed + " " + e.message);
    } finally {
      setVoicesLoading(false);
    }
  };

  const playPreview = (voiceId, url) => {
    if (!url) return;
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.currentTime = 0;
    }
    if (playingVoiceId === voiceId) {
      setPlayingVoiceId(null);
      return;
    }
    const a = new Audio(url);
    previewAudioRef.current = a;
    a.onended = () => setPlayingVoiceId(null);
    a.play().catch(() => setPlayingVoiceId(null));
    setPlayingVoiceId(voiceId);
  };

  const filteredVoices = React.useMemo(() => {
    if (!voicesList) return [];
    return voicesList.filter((v) => {
      const lbl = v.labels || {};
      if (voicesFilter.language !== "any") {
        const lang = (lbl.language || "").toLowerCase();
        // ElevenLabs labels часто пустые — пропускаем без language если язык "any"
        if (lang && !lang.includes(voicesFilter.language)) return false;
      }
      if (voicesFilter.gender !== "any") {
        const g = (lbl.gender || "").toLowerCase();
        if (g && g !== voicesFilter.gender) return false;
      }
      if (voicesFilter.search) {
        const s = voicesFilter.search.toLowerCase();
        const hay = (v.name + " " + (v.description || "") + " " + JSON.stringify(lbl)).toLowerCase();
        if (!hay.includes(s)) return false;
      }
      return true;
    });
  }, [voicesList, voicesFilter]);
  const fileInputRef = React.useRef(null);

  // Запоминаем размер последнего выбранного файла чтобы показать в чипе.
  const [fileSize, setFileSize] = React.useState(0);
  const onDrop = (e) => {
    e.preventDefault(); setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setFile(f.name, f);
      setFileSize(f.size || 0);
    }
  };
  const _fmtMB = (b) => {
    if (!b) return "";
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
    if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
    return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
  };

  const activeStyle = SUBTITLE_STYLES.find(s => s.id === subtitleStyleId);
  const activeLLM = LLM_PROVIDERS.find(p => p.id === llmProviderId);
  const activeCTA = CTA_PRESETS.find(c => c.id === ctaPresetId);

  return (
    <div className="glass" style={{ padding: 26 }}>
      {/* Step 1: Source */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "stretch" }}>
        <div style={{ position: "relative" }}>
          <input
            className="input"
            placeholder={t.urlPlaceholder}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            style={{ paddingRight: file ? 110 : 14, height: 52, fontSize: 15 }}
          />
          {file && (
            <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)" }}>
              <span className="chip" style={{ background: "rgba(198,255,61,0.18)", borderColor: "rgba(198,255,61,0.5)" }}>
                {file.length > 16 ? file.slice(0, 16) + "…" : file}
                {fileSize > 0 && <span style={{ color: "var(--muted)", marginLeft: 6 }}>· {_fmtMB(fileSize)}</span>}
                <button className="btn-link muted" onClick={() => { setFile("", null); setFileSize(0); }} style={{ marginLeft: 4 }}>
                  <Icon name="x" size={11}/>
                </button>
              </span>
            </span>
          )}
        </div>
        <button
          className="btn btn-ghost"
          onClick={() => fileInputRef.current?.click()}
          style={{ height: 52, padding: "0 16px" }}
        >
          <Icon name="upload" size={14}/> {t.fileBtn}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="video/*,.mp4,.mov,.mkv,.webm,.avi,.m4v,.flv"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) { setFile(f.name, f); setFileSize(f.size || 0); }
          }}
        />
      </div>

      <div className="row" style={{ gap: 10, marginTop: 14, flexWrap: "wrap", alignItems: "center" }}>
        <div className="row" style={{ gap: 8 }}>
          <span className="label" style={{ margin: 0 }}>{t.clipsCount}</span>
          <div className="seg">
            {[5, 8, 10, 15].map(n => (
              <button key={n} className={maxClips === n ? "on" : ""} onClick={() => setMaxClips(n)}>{n}</button>
            ))}
          </div>
        </div>
        <div style={{ flex: 1 }}></div>
        <div style={{ fontSize: 12, color: "var(--muted)" }}>
          {t.etaHint}
        </div>
      </div>

      {/* Per-video AI instruction (picker hint) */}
      <PickerExtraField t={t} value={pickerExtra} onChange={setPickerExtra}/>

      {/* Step 2: Subtitle style */}
      <div style={{ marginTop: 22 }}>
        <div className="label-row">
          <label className="label">{t.subtitleStyle}</label>
          <span style={{ fontSize: 12, color: "var(--muted-2)" }}>{activeStyle?.name}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
          {SUBTITLE_STYLES.map((s) => {
            const isActive = subtitleStyleId === s.id;
            const label =
              s.id === "karaoke" ? "Karaoke" :
              s.id === "block" ? "Block" :
              s.id === "minimal" ? "Minimal" :
              s.id === "neon" ? "Neon" :
              s.id === "telegram" ? "Telegram" : "Big white";
            const desc =
              s.id === "karaoke" ? t.subStyleKaraoke :
              s.id === "block" ? t.subStyleByPhrase :
              s.id === "minimal" ? t.subStyleMinimal :
              s.id === "neon" ? t.subStyleNeon :
              s.id === "telegram" ? t.subStyleTelegram : t.subStyleBigwhite;
            return (
              <button
                key={s.id}
                onClick={() => setSubtitleStyleId(s.id)}
                style={{
                  cursor: "pointer",
                  padding: 10,
                  borderRadius: 14,
                  border: isActive ? "2px solid var(--ink)" : "1px solid var(--line)",
                  background: isActive ? "var(--bg-3)" : "var(--bg-2)",
                  boxShadow: isActive
                    ? "0 0 0 3px var(--lime), 0 8px 20px rgba(10,13,10,0.12)"
                    : "0 1px 0 rgba(255,255,255,0.6) inset",
                  display: "flex", flexDirection: "column", gap: 8,
                  textAlign: "left",
                  transition: "transform .12s ease, box-shadow .15s ease",
                }}
              >
                {/* Mini 9:16 frame with realistic dark gradient */}
                <div style={{
                  height: 76,
                  borderRadius: 10,
                  background:
                    "linear-gradient(180deg, #2b2f36 0%, #1a1d23 60%, #0c0e12 100%)",
                  position: "relative",
                  overflow: "hidden",
                  display: "flex", alignItems: "flex-end", justifyContent: "center",
                  paddingBottom: 10,
                }}>
                  {/* faux talking-head silhouette */}
                  <div style={{
                    position: "absolute",
                    left: "50%", bottom: -8, transform: "translateX(-50%)",
                    width: "60%", height: "70%",
                    background: "radial-gradient(50% 50% at 50% 30%, rgba(255,210,180,0.55), transparent 70%)",
                    borderRadius: "50% 50% 0 0",
                    filter: "blur(2px)",
                  }}/>
                  <SubtitlePreview id={s.id}/>
                </div>
                <div className="row-between" style={{ alignItems: "center" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--ink)", lineHeight: 1.2 }}>{label}</div>
                    <div style={{ fontSize: 10.5, color: "var(--muted)", marginTop: 2, lineHeight: 1.2 }}>{desc}</div>
                  </div>
                  {isActive && (
                    <span style={{
                      width: 18, height: 18, borderRadius: 99,
                      background: "var(--lime)", color: "var(--ink)",
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0,
                    }}>
                      <Icon name="check" size={11}/>
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Collapsed sections */}
      <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 10 }}>

        {/* LLM provider */}
        <div className="collapse">
          <button className="collapse-head" onClick={() => setShowLLM(!showLLM)}>
            <span>
              {t.llmProviderAccordion}
              <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 10 }}>
                · {activeLLM?.name}
              </span>
            </span>
            <span className={"caret " + (showLLM ? "open" : "")}>›</span>
          </button>
          {showLLM && (
            <div className="collapse-body" style={{ paddingTop: 14, paddingBottom: 16 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
                {LLM_PROVIDERS.map((p) => (
                  <button
                    key={p.id}
                    className={"provider " + (llmProviderId === p.id ? "active" : "")}
                    onClick={() => setLlmProviderId(p.id)}
                  >
                    <div>
                      <div className="prov-name">
                        {p.name}
                        {!p.configured && <span className="badge-warn">{t.badgeNotConfigured}</span>}
                      </div>
                      <div className="prov-sub">{p.sub}</div>
                    </div>
                    <div className="prov-badge">{p.id.includes("api") ? t.badgeApi : t.badgeSubscription}</div>
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 12 }}>
                <label className="label">{t.modelLabel}</label>
                <select className="select" value={llmModel} onChange={(e) => setLlmModel(e.target.value)}>
                  <option value="">{t.modelAutoFastCheap}</option>
                  <option value="claude-haiku-4-5-20251001">{t.modelHaikuFast}</option>
                  <option value="claude-sonnet-4-6-20251008">{t.modelSonnetBalance}</option>
                  <option value="claude-opus-4-7">{t.modelOpusFlagship}</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* CTA */}
        <div className="collapse">
          <button className="collapse-head" onClick={() => setShowCTA(!showCTA)}>
            <span>
              {t.ctaAccordion}
              <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 10 }}>
                · {activeCTA?.title}
              </span>
            </span>
            <span className={"caret " + (showCTA ? "open" : "")}>›</span>
          </button>
          {showCTA && (
            <div className="collapse-body">
              <div className="row-between" style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
                  {t.ctaBrandLine} <strong style={{ color: "var(--ink)" }}>{brand}</strong> · {t.ctaPresetsEdit}
                </div>
                <span style={{ fontSize: 11, color: "var(--muted-2)" }}>
                  {activeCTA?.id === "none" ? t.noCtaShort : t.ctaWillShow}
                </span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
                {CTA_PRESETS.map((c) => {
                  const isActive = ctaPresetId === c.id;
                  const isNone = c.id === "none";
                  return (
                    <button
                      key={c.id}
                      onClick={() => setCtaPresetId(c.id)}
                      style={{
                        cursor: "pointer",
                        padding: 12,
                        borderRadius: 14,
                        border: isActive ? "2px solid var(--ink)" : "1px solid var(--line)",
                        background: isActive ? "var(--bg-3)" : "var(--bg-2)",
                        boxShadow: isActive
                          ? "0 0 0 3px var(--lime), 0 8px 20px rgba(10,13,10,0.12)"
                          : "0 1px 0 rgba(255,255,255,0.6) inset",
                        display: "flex", flexDirection: "column", gap: 10,
                        textAlign: "left",
                        minHeight: 132,
                        transition: "transform .12s ease, box-shadow .15s ease",
                      }}
                    >
                      {/* Mini visual: end-card mockup */}
                      <div style={{
                        height: 56,
                        borderRadius: 10,
                        background: isNone
                          ? "repeating-linear-gradient(45deg, var(--bg-2) 0 8px, var(--bg-3) 8px 16px)"
                          : "linear-gradient(180deg, #1a1d23 0%, #0c0e12 100%)",
                        position: "relative",
                        overflow: "hidden",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        padding: "0 8px",
                      }}>
                        {isNone ? (
                          <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 600 }}>—</span>
                        ) : (
                          <div style={{
                            background: "var(--lime)", color: "var(--ink)",
                            padding: "5px 10px", borderRadius: 6,
                            fontFamily: "var(--font-display)", fontWeight: 800,
                            fontSize: 11, letterSpacing: "0.01em",
                            textAlign: "center", lineHeight: 1.15,
                            maxWidth: "100%",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          }}>{c.title}</div>
                        )}
                      </div>
                      <div className="row-between" style={{ alignItems: "flex-start" }}>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--ink)", lineHeight: 1.3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.title}</div>
                          <div className="mono" style={{ fontSize: 10.5, color: "var(--muted)", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.url || t.noLink}</div>
                        </div>
                        {isActive && (
                          <span style={{
                            width: 18, height: 18, borderRadius: 99,
                            background: "var(--lime)", color: "var(--ink)",
                            display: "inline-flex", alignItems: "center", justifyContent: "center",
                            flexShrink: 0, marginLeft: 6,
                          }}>
                            <Icon name="check" size={11}/>
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Advanced */}
        <div className="collapse">
          <button className="collapse-head" onClick={() => setShowAdvanced(!showAdvanced)}>
            <span>
              {t.advancedAccordion}
              <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 10 }}>
                · {t.advancedAccordionHint}
              </span>
            </span>
            <span className={"caret " + (showAdvanced ? "open" : "")}>›</span>
          </button>
          {showAdvanced && (
            <div className="collapse-body">
              <div className="grid-2">
                <div>
                  <label className="label">{t.whisperModel}</label>
                  <select className="select" value={whisperModel} onChange={(e) => setWhisperModel(e.target.value)}>
                    <option value="auto">{t.optionAutoHardware}</option>
                    <option value="tiny">tiny · 39 MB</option>
                    <option value="base">base · 74 MB</option>
                    <option value="small">small · 244 MB</option>
                    <option value="medium">medium · 769 MB</option>
                    <option value="large-v3">large-v3 · 1.5 GB</option>
                    <option value="large-v3-turbo">large-v3-turbo · 809 MB</option>
                  </select>
                </div>
                <div>
                  <label className="label">{t.downloadQualityLabel}</label>
                  <select className="select" value={downloadMax} onChange={(e) => setDownloadMax(e.target.value)}>
                    <option value="auto">{t.optionAuto}</option>
                    <option value="1080p">1080p</option>
                    <option value="720p">720p</option>
                    <option value="480p">480p</option>
                    <option value="360p">{t.option360Fast}</option>
                  </select>
                </div>
                <div>
                  <label className="label">{t.outputSize}</label>
                  <select className="select" value={outputSize} onChange={(e) => setOutputSize(e.target.value)}>
                    <option value="auto">{t.optionAutoNoUpscale}</option>
                    <option value="1080x1920">1080×1920</option>
                    <option value="720x1280">720×1280</option>
                    <option value="540x960">540×960</option>
                  </select>
                </div>
                <div>
                  <label className="label">Cookies</label>
                  <select className="select" value={cookies} onChange={(e) => setCookies(e.target.value)}>
                    <option value="none">{t.noCookies}</option>
                    <option value="chrome">Chrome</option>
                    <option value="safari">Safari</option>
                    <option value="firefox">Firefox</option>
                  </select>
                </div>
              </div>
              <div className="hint" style={{ marginTop: 12 }}>
                {t.autoNativeHint}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Voiceover */}
      <div style={{ marginTop: 14 }}>
        <div className="collapse">
          <button
            className="collapse-head"
            onClick={() => setShowVoiceover((v) => !v)}
            type="button"
          >
            <span>
              🎙 {t.voiceoverAccordion}
              <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 10 }}>
                {voiceover
                  ? `· ${t.voiceoverEnabledPrefix} · ${voiceoverEngine === "clone" ? "clone" : "library"} → ${voiceoverTargetLang}`
                  : `· ${t.voiceoverDisabledHint}`}
              </span>
            </span>
            <span className={"caret " + (showVoiceover ? "open" : "")}>›</span>
          </button>
          {showVoiceover && (
            <div className="collapse-body">
              <label className="row" style={{ gap: 10, alignItems: "center", marginBottom: 14, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={voiceover}
                  onChange={(e) => setVoiceover(e.target.checked)}
                  style={{ width: 18, height: 18 }}
                />
                <span style={{ fontWeight: 600 }}>{t.voiceoverEnable}</span>
                <span style={{ fontSize: 12, color: "var(--muted)" }}>
                  {t.voiceoverDescDub}
                </span>
              </label>

              {voiceover && (
                <>
                  <label className="label">{t.voiceoverEngine}</label>
                  <div className="grid-2" style={{ marginBottom: 14 }}>
                    <label
                      className={"provider " + (voiceoverEngine === "clone" ? "active" : "")}
                      style={{ cursor: "pointer", padding: 12 }}
                    >
                      <input
                        type="radio"
                        name="voiceover_engine"
                        checked={voiceoverEngine === "clone"}
                        onChange={() => setVoiceoverEngine("clone")}
                        style={{ display: "none" }}
                      />
                      <div style={{ fontWeight: 600, fontSize: 13 }}>Clone — Dubbing API ⭐</div>
                      <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>
                        {t.cloneDescription}
                      </div>
                    </label>
                    <label
                      className={"provider " + (voiceoverEngine === "library" ? "active" : "")}
                      style={{ cursor: "pointer", padding: 12 }}
                    >
                      <input
                        type="radio"
                        name="voiceover_engine"
                        checked={voiceoverEngine === "library"}
                        onChange={() => setVoiceoverEngine("library")}
                        style={{ display: "none" }}
                      />
                      <div style={{ fontWeight: 600, fontSize: 13 }}>Library — TTS</div>
                      <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>
                        {t.libraryDescription}
                      </div>
                    </label>
                  </div>

                  <div className="grid-2" style={{ marginBottom: 14 }}>
                    <div>
                      <label className="label">{t.voiceoverTargetLang}</label>
                      <select
                        className="select"
                        value={voiceoverTargetLang}
                        onChange={(e) => setVoiceoverTargetLang(e.target.value)}
                      >
                        <option value="ru">{t.langRu}</option>
                        <option value="en">english</option>
                        <option value="es">español</option>
                        <option value="de">deutsch</option>
                        <option value="fr">français</option>
                        <option value="zh">中文</option>
                      </select>
                    </div>
                    {voiceoverEngine === "library" && (
                      <div>
                        <label className="label">{t.voiceoverModeLabel}</label>
                        <select
                          className="select"
                          value={voiceoverMode}
                          onChange={(e) => setVoiceoverMode(e.target.value)}
                        >
                          <option value="duck">{t.duckMode}</option>
                          <option value="replace">{t.replaceMode}</option>
                        </select>
                      </div>
                    )}
                  </div>

                  {voiceoverEngine === "library" && (
                    <>
                      <div className="grid-2">
                        <div>
                          <label className="label">{t.voiceoverTtsModel}</label>
                          <select
                            className="select"
                            value={voiceoverModel}
                            onChange={(e) => setVoiceoverModel(e.target.value)}
                          >
                            <option value="eleven_v3">{t.ttsV3}</option>
                            <option value="eleven_multilingual_v2">Multilingual v2</option>
                            <option value="eleven_flash_v2_5">{t.ttsFlash}</option>
                          </select>
                        </div>
                        <div>
                          <label className="label">{t.voiceoverVoice}</label>
                          <input
                            className="input mono"
                            value={voiceoverVoice}
                            onChange={(e) => setVoiceoverVoice(e.target.value)}
                            placeholder="EXAVITQu4vr4xnSDxMaL"
                          />
                        </div>
                      </div>

                      <div style={{ marginTop: 14 }}>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                          <label className="label" style={{ margin: 0 }}>
                            {t.voicesFromLib}
                            {voicesList && <span style={{ color: "var(--muted)", marginLeft: 8, fontSize: 11 }}>· {filteredVoices.length} {t.voicesCountOf} {voicesList.length}</span>}
                          </label>
                          <button
                            type="button"
                            className="btn"
                            onClick={loadVoices}
                            disabled={voicesLoading}
                            style={{ padding: "4px 10px", fontSize: 12 }}
                          >
                            {voicesLoading ? "…" : voicesList ? t.voicesRefresh : t.voicesLoad}
                          </button>
                        </div>
                        {voicesList && (
                          <>
                            <div className="grid-2" style={{ marginTop: 8, gap: 6 }}>
                              <select
                                className="select"
                                value={voicesFilter.gender}
                                onChange={(e) => setVoicesFilter((f) => ({ ...f, gender: e.target.value }))}
                                style={{ fontSize: 12 }}
                              >
                                <option value="any">{t.voiceGenderAny}</option>
                                <option value="male">{t.voiceGenderMale}</option>
                                <option value="female">{t.voiceGenderFemale}</option>
                                <option value="non-binary">non-binary</option>
                              </select>
                              <input
                                className="input"
                                placeholder={t.voicesSearchPlaceholder}
                                value={voicesFilter.search}
                                onChange={(e) => setVoicesFilter((f) => ({ ...f, search: e.target.value }))}
                                style={{ fontSize: 12 }}
                              />
                            </div>
                            <div style={{
                              maxHeight: 280,
                              overflowY: "auto",
                              marginTop: 8,
                              background: "var(--paper-2)",
                              borderRadius: 8,
                              padding: 6,
                            }}>
                              {filteredVoices.length === 0 && (
                                <div style={{ fontSize: 12, color: "var(--muted)", padding: 8, textAlign: "center" }}>
                                  {t.voicesNothingFound}
                                </div>
                              )}
                              {filteredVoices.map((v) => {
                                const isActive = voiceoverVoice === v.voice_id;
                                const lbl = v.labels || {};
                                return (
                                  <div
                                    key={v.voice_id}
                                    onClick={() => setVoiceoverVoice(v.voice_id)}
                                    style={{
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 8,
                                      padding: "6px 8px",
                                      borderRadius: 6,
                                      cursor: "pointer",
                                      background: isActive ? "rgba(198,255,61,0.18)" : "transparent",
                                      marginBottom: 2,
                                    }}
                                  >
                                    <button
                                      type="button"
                                      className="btn"
                                      onClick={(e) => { e.stopPropagation(); playPreview(v.voice_id, v.preview_url); }}
                                      disabled={!v.preview_url}
                                      style={{ padding: "2px 8px", fontSize: 11, minWidth: 28 }}
                                      title={v.preview_url ? t.voicesPlayPreview : t.voicesNoPreview}
                                    >
                                      {playingVoiceId === v.voice_id ? "⏸" : "▶"}
                                    </button>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                      <div style={{ fontWeight: 600, fontSize: 13 }}>
                                        {v.name}
                                        {isActive && <span style={{ color: "var(--lime-deep)", marginLeft: 6 }}>✓</span>}
                                      </div>
                                      <div style={{ fontSize: 11, color: "var(--muted)" }}>
                                        {[lbl.gender, lbl.age, lbl.accent, lbl.use_case, lbl.language].filter(Boolean).join(" · ") || v.category || "—"}
                                      </div>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </>
                        )}
                      </div>
                    </>
                  )}

                  <div className="hint" style={{ marginTop: 12 }}>
                    {voiceoverEngine === "clone"
                      ? t.cloneFullDesc
                      : t.libraryFullDesc}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Action */}
      <div style={{ marginTop: 22, display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
        <button
          className="btn btn-primary"
          style={{ padding: "13px 22px", fontSize: 14.5, borderRadius: 14 }}
          onClick={onCut}
          disabled={cutting || (!url && !file)}
        >
          <Icon name="scissors" size={14}/>
          {cutting ? t.cutting : t.cutNow}
        </button>
      </div>
    </div>
  );
}

// ── PickerExtraField — per-video override для picker'а ──
// Передаётся в /jobs как form-поле picker_extra → src/picker.py добавляет его
// в системный промпт как приоритетную инструкцию для конкретного прогона.
function PickerExtraField({ t, value, onChange }) {
  const { Icon } = window.UI;
  const [open, setOpen] = React.useState(!!(value && value.trim()));
  const examples = [
    t.pickerExtraEx1,
    t.pickerExtraEx2,
    t.pickerExtraEx3,
    t.pickerExtraEx4,
  ];
  const trimmed = (value || "").trim();
  return (
    <div className="collapse" style={{ marginTop: 14 }}>
      <button className="collapse-head" onClick={() => setOpen(!open)} type="button">
        <span>
          <Icon name="sparkles" size={13}/> {t.pickerExtraLabel}
          <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 10 }}>
            · {trimmed
                ? (trimmed.length > 60 ? trimmed.slice(0, 60) + "…" : trimmed)
                : t.pickerExtraSub}
          </span>
        </span>
        <span className={"caret " + (open ? "open" : "")}>›</span>
      </button>
      {open && (
        <div className="collapse-body" style={{ paddingTop: 14, paddingBottom: 16 }}>
          <textarea
            className="textarea"
            placeholder={t.pickerExtraPlaceholder}
            value={value || ""}
            onChange={(e) => onChange(e.target.value)}
            rows={3}
            maxLength={1500}
            style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}
          />
          <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between",
                        fontSize: 11.5, color: "var(--muted)" }}>
            <span>{t.pickerExtraHint}</span>
            <span style={{ fontFamily: "var(--font-mono)", flexShrink: 0, marginLeft: 12 }}>
              {(value || "").length}/1500
            </span>
          </div>

          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 11.5, color: "var(--muted)", marginBottom: 6, fontWeight: 600 }}>
              {t.pickerExtraExamplesTitle}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {examples.map((ex, i) => (
                <button
                  key={i}
                  type="button"
                  className="chip"
                  onClick={() => onChange(ex)}
                  style={{
                    fontSize: 11.5, padding: "4px 10px", cursor: "pointer",
                    background: "var(--bg-3)", maxWidth: "100%",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}
                  title={ex}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          {trimmed && (
            <div style={{
              marginTop: 12, padding: "8px 12px", borderRadius: 8,
              background: "rgba(198,255,61,0.15)",
              border: "1px solid rgba(198,255,61,0.4)",
              fontSize: 12, color: "var(--ink)",
            }}>
              {t.pickerExtraApplied}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SubtitlePreview({ id }) {
  switch (id) {
    case "karaoke":  return <span className="sub-preview sub-karaoke">мо<span className="hl">мент</span></span>;
    case "block":    return <span className="sub-preview sub-block">фраза</span>;
    case "minimal":  return <span className="sub-preview sub-minimal">мин</span>;
    case "neon":     return <span className="sub-preview sub-neon">неон</span>;
    case "telegram": return <span className="sub-preview sub-telegram">эфир</span>;
    case "bigwhite": return <span className="sub-preview sub-bigwhite">х10</span>;
    default: return null;
  }
}

window.HEROCUT = { HeroBlock, CutForm };
