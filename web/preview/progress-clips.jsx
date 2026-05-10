// Cutting progress + ready-clips list

// Helper для компонентов которые не получают `t` через props.
// Берёт текущий язык из window.MOCK.tweaks.lang.
function _i18n() {
  return window.I18N[(window.MOCK && window.MOCK.tweaks && window.MOCK.tweaks.lang) || "ru"]
       || window.I18N.ru;
}

function ProgressBlock({ percent, log, onCancel }) {
  const t = _i18n();
  const { Icon } = window.UI;
  const logRef = React.useRef(null);
  // ⭐ auto-scroll лог к низу при каждом новом сообщении — актуальные внизу
  React.useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log]);

  // показываем только последние 200 строк — иначе DOM пухнет на длинных job'ах
  const visibleLog = log.length > 200 ? log.slice(-200) : log;

  return (
    <div className="glass" style={{ padding: 22, position: "sticky", top: 12, zIndex: 5 }}>
      <div className="row-between" style={{ marginBottom: 14 }}>
        <div>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 22, letterSpacing: "-0.02em" }}>
            {t.cutting}
          </div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            Whisper-large-v3 · MLX · ~30× realtime · {percent < 100 ? t.pipelineStages : t.pipelineDone}
          </div>
        </div>
        <div className="row" style={{ gap: 12 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 28, letterSpacing: "-0.02em" }}>
            {Math.round(percent)}%
          </div>
          <button className="btn btn-ghost" onClick={onCancel}>
            <Icon name="x" size={14}/> {t.cancel}
          </button>
        </div>
      </div>
      <div className="progress" style={{ height: 10, marginBottom: 18 }}>
        <div className="progress-bar" style={{ width: `${percent}%` }}></div>
      </div>
      <div
        ref={logRef}
        className="log"
        style={{ maxHeight: 320, overflowY: "auto", scrollBehavior: "smooth" }}
      >
        {visibleLog.map((line, i) => (
          <div key={i}>
            <span className="l-meta">{line.t}</span>{" "}
            <span className={line.ok ? "l-ok" : ""}>{line.msg}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RecentJobs({ t, onClick, onDeleted }) {
  const [list, setList] = React.useState(() => window.MOCK.RECENT_JOBS || []);
  const [busyId, setBusyId] = React.useState("");
  const { Icon } = window.UI;

  // подхватываем обновления MOCK.RECENT_JOBS из app.jsx (после нарезки)
  React.useEffect(() => {
    setList(window.MOCK.RECENT_JOBS || []);
  }, [window.MOCK.RECENT_JOBS]);

  const removeJob = async (e, j) => {
    e.stopPropagation();   // не запускать onClick карточки
    if (!j._id) return;
    if (!confirm(`Удалить задание «${(j.title || "").slice(0, 40)}…»? Файлы клипов и мастеры будут удалены с диска.`)) return;
    setBusyId(j._id);
    try {
      await window.API.deleteJob(j._id);
      const fresh = await window.API.jobs(30);
      const mapped = fresh.map((it) => ({
        title: it.title || it.source_url || it.id,
        count: it.n_clips || 0,
        _id: it.id, _status: it.status, _stage: it.stage, _error: it.error,
      }));
      window.MOCK.RECENT_JOBS = mapped;
      setList(mapped);
      onDeleted?.();
    } catch (err) {
      alert(`Не удалилось: ${err.message}`);
    } finally { setBusyId(""); }
  };

  // status → цвет/текст бейджа
  const badgeFor = (j) => {
    const s = j._status;
    if (s === "running") return { cls: "badge-warn", style: { background: "rgba(198,255,61,0.2)", color: "var(--ink)" }, text: t.statusRunning };
    if (s === "error") return { cls: "badge-warn", style: undefined, text: t.statusError };
    if (s === "done") return { cls: "badge-ok", style: undefined, text: t.statusDone };
    if (s === "queued" || s === "pending") return { cls: "chip", style: { fontSize: 11 }, text: t.statusQueued };
    return null;
  };

  return (
    <div style={{ marginTop: 28 }}>
      <div className="section-h">
        <h3>{t.recentJobs}</h3>
        <span className="meta">{list.length} · сохранено локально</span>
      </div>
      {list.length === 0 ? (
        <div className="hint">
          Заданий пока нет. Вставь YouTube-ссылку выше и нажми «Нарезать» — здесь появится первый.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 10 }}>
          {list.map((j) => {
            const badge = badgeFor(j);
            const isBusy = busyId === j._id;
            return (
              <div
                key={j._id || j.title}
                className="job-card"
                onClick={() => onClick(j)}
                style={{ textAlign: "left", cursor: "pointer", opacity: isBusy ? 0.5 : 1 }}
                role="button"
              >
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="row" style={{ gap: 8, marginBottom: 4 }}>
                    {badge && (
                      badge.cls === "chip"
                        ? <span className="chip" style={badge.style}>{badge.text}</span>
                        : <span className={badge.cls} style={badge.style}>{badge.text}</span>
                    )}
                  </div>
                  <div className="job-title" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {j.title}
                  </div>
                  <div className="job-meta">
                    {j._error
                      ? <span style={{ color: "var(--danger)" }}>{j._error.slice(0, 60)}</span>
                      : `${j.count} клипов`}
                  </div>
                </div>
                <div className="row" style={{ gap: 8, flexShrink: 0 }}>
                  <span className="chip">
                    <Icon name="play" size={12}/> {j.count}
                  </span>
                  <button
                    className="icon-btn"
                    title={t.deleteJob}
                    onClick={(e) => removeJob(e, j)}
                    disabled={isBusy}
                    style={{ width: 28, height: 28 }}
                  >
                    <Icon name="x" size={12}/>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Извлекает все URL'ы из строки. Поддерживает http(s)://… и доменное короткое (excella.ru/...).
function _extractUrls(text) {
  if (!text) return [];
  // абсолютные http(s):// и протоколо-меньшие домены вроде excella.ru/cases
  const re = /\bhttps?:\/\/\S+|\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/\S*)?/gi;
  return [...new Set((text.match(re) || []).map((u) => u.replace(/[),.;]+$/, "")))];
}

function ClipCard({ clip, t, onPublish, onMetrics, onChangeStyle, publishStatus = {} }) {
  const { Icon } = window.UI;
  const [tab, setTab] = React.useState("seo");
  const [openTrim, setOpenTrim] = React.useState(false);
  const [openReframe, setOpenReframe] = React.useState(false);
  const [openMusic, setOpenMusic] = React.useState(false);
  const [openBroll, setOpenBroll] = React.useState(false);
  const [openThumbs, setOpenThumbs] = React.useState(false);
  const [copied, setCopied] = React.useState("");
  // controlled state для description/hashtags чтобы парсер ссылок реагировал на ввод
  const [descText, setDescText] = React.useState(clip.description || "");
  const [tagsText, setTagsText] = React.useState(clip.hashtags || "");
  React.useEffect(() => { setDescText(clip.description || ""); }, [clip.id, clip.description]);
  React.useEffect(() => { setTagsText(clip.hashtags || ""); }, [clip.id, clip.hashtags]);
  const descUrls = React.useMemo(() => _extractUrls(descText), [descText]);
  const SUBTITLE_STYLES = window.MOCK.SUBTITLE_STYLES || [];
  const activeStyle = SUBTITLE_STYLES.find((s) => s.id === clip.activeStyle) || SUBTITLE_STYLES[0] || { id: "block" };

  // ── реальный URL мастер-видео если оно есть в backend ──
  // _files: {1080p:..., 720p:..., 480p:...}; берём самый большой как master.
  const _files = clip._files || {};
  const _masterFile = ["1080p", "720p", "480p"]
    .map((k) => _files[k])
    .find(Boolean);
  const videoUrl = clip._jobId && _masterFile
    ? window.API.clipUrl(clip._jobId, _masterFile)
    : null;

  const copy = (k, txt) => {
    navigator.clipboard?.writeText(txt);
    setCopied(k);
    setTimeout(() => setCopied(""), 1200);
  };

  return (
    <div className="glass clip-card">
      {/* Poster preview */}
      <div className={"clip-poster " + clip.poster}>
        {videoUrl ? (
          // Реальный <video> — играется по клику, preload metadata для тонкого графика длительности
          <video
            className="poster-video"
            src={videoUrl}
            playsInline
            controls
            preload="metadata"
            poster={clip._jobId && clip._slug
              ? window.API.thumbUrl(clip._jobId, `${clip._slug}/0.jpg`)
              : undefined}
            style={{
              position: "absolute", inset: 0, width: "100%", height: "100%",
              objectFit: "cover", background: "#000",
            }}
          />
        ) : (
          <>
            <div className="poster-fill"></div>
            <div className="poster-figure"></div>
            <PosterCaption clip={clip} style={activeStyle} />
            <div className="poster-face"></div>
            <div className="poster-controls">
              <span className="poster-play"><Icon name="play" size={11}/></span>
              <span>0:14</span>
              <div className="poster-bar"></div>
              <span>{clip.duration}</span>
            </div>
          </>
        )}
        <span className="poster-tag" style={{ zIndex: 2 }}>{String(clip.n).padStart(2, "0")}</span>
        <div className="poster-watermark" style={{ zIndex: 2 }}>
          <svg width="48" height="11" viewBox="0 0 114 26" fill="none">
            <path d="M17.7347 10.6542V15.2358H3.19173V10.6542H17.7347ZM7.74766 12.945L6.56364 20.1264L4.04114 17.3465H18.6871V19.4081L15.8851 22.5974H0L1.41569 12.945L0 3.2926H21.8081L26.0795 8.54351H4.04114L6.56364 5.76362L7.74766 12.945Z" fill="#0A0D0A"/>
            <path d="M34.4862 11.8255V7.73287L44.2673 19.8048H36.1078L30.3421 12.1601H33.6883L22.1759 25.5H14.1194L29.6729 7.73287V11.8255L20.3036 0.5H28.6176L33.817 7.37251H30.4708L35.5673 0.5H43.7783L34.4862 11.8255Z" fill="#0A0D0A"/>
          </svg>
        </div>
      </div>

      {/* Right side */}
      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div className="row-between" style={{ marginBottom: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase" }}>
              Клип #{clip.n} · {clip.range} · {clip.duration}
            </div>
            <div className="h-section" style={{ fontSize: 22, marginTop: 4, lineHeight: 1.15 }}>
              {clip.title}
            </div>
          </div>
          <div className="row" style={{ gap: 6 }}>
            <a
              href={videoUrl || "#"}
              download={_masterFile || undefined}
              className="icon-btn"
              title={t.download}
              onClick={(e) => { if (!videoUrl) e.preventDefault(); }}
              style={!videoUrl ? { opacity: 0.5, pointerEvents: "none" } : undefined}
            >
              <Icon name="download" size={14}/>
            </a>
            <button className="icon-btn" title={t.metricsBtn} onClick={() => onMetrics(clip)}>
              <Icon name="chart" size={14}/>
            </button>
          </div>
        </div>

        <div className="text-tabs">
          <button className={"text-tab " + (tab === "seo" ? "active" : "")} onClick={() => setTab("seo")}>
            {t.tabSeo}
          </button>
          <button className={"text-tab " + (tab === "edit" ? "active" : "")} onClick={() => setTab("edit")}>
            {t.tabEdit}
          </button>
          <button className={"text-tab " + (tab === "regen" ? "active" : "")} onClick={() => setTab("regen")}>
            {t.tabRegen}
          </button>
          <button className={"text-tab " + (tab === "effects" ? "active" : "")} onClick={() => setTab("effects")}>
            {t.tabEffects}
          </button>
          <button className={"text-tab " + (tab === "publish" ? "active" : "")} onClick={() => setTab("publish")}>
            {t.tabPublish}
          </button>
        </div>

        {tab === "seo" && (
          <div>
            <div style={{ marginBottom: 14 }}>
              <div className="label-row">
                <label className="label">{t.title} <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {clip.title.length}/60</span></label>
                <button className="btn-link muted" onClick={() => copy("title", clip.title)}>
                  <Icon name="copy" size={12}/> {copied === "title" ? t.copied : t.copy}
                </button>
              </div>
              <input className="input" defaultValue={clip.title} />
            </div>
            <div style={{ marginBottom: 14 }}>
              <div className="label-row">
                <label className="label">{t.description}</label>
                <button className="btn-link muted" onClick={() => copy("desc", descText)}>
                  <Icon name="copy" size={12}/> {copied === "desc" ? t.copied : t.copy}
                </button>
              </div>
              <textarea
                className="textarea"
                value={descText}
                onChange={(e) => setDescText(e.target.value)}
              />
              {descUrls.length > 0 && (
                <div style={{
                  display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6,
                  fontSize: 12, color: "var(--muted)",
                }}>
                  <span style={{ alignSelf: "center" }}>{t.linksInDescription}</span>
                  {descUrls.map((u) => {
                    const href = u.startsWith("http") ? u : `https://${u}`;
                    return (
                      <a
                        key={u}
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                        className="chip"
                        style={{
                          color: "var(--ink)", textDecoration: "none",
                          fontSize: 11.5, fontFamily: "var(--font-mono)",
                          padding: "3px 9px", maxWidth: 360,
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}
                      >
                        ↗ {u}
                      </a>
                    );
                  })}
                </div>
              )}
              <div className="help">
                В <code style={{ fontFamily: "var(--font-mono)" }}>{`<textarea>`}</code> ссылки не кликабельны — это нативное поведение HTML.
                В YouTube/VK/Instagram URL автоматически становятся кликабельными при публикации.
              </div>
            </div>
            <div style={{ marginBottom: 14 }}>
              <div className="label-row">
                <label className="label">{t.hashtags}</label>
                <button className="btn-link muted" onClick={() => copy("tags", tagsText)}>
                  <Icon name="copy" size={12}/> {copied === "tags" ? t.copied : t.copy}
                </button>
              </div>
              <textarea
                className="textarea"
                style={{ minHeight: 64 }}
                value={tagsText}
                onChange={(e) => setTagsText(e.target.value)}
              />
            </div>

            <UniquifyPanel clip={clip} t={t} Icon={Icon}/>
            {/* старые статичные карточки скрыты — UniquifyPanel выше делает реальную генерацию */}
            <div style={{ display: "none" }}>
              {[].map((p) => (
                  <div key={p.id} style={{
                    padding: 12,
                    borderRadius: 12,
                    background: "var(--bg-3)",
                    border: "1px solid var(--line)",
                    display: "flex", flexDirection: "column", gap: 8,
                    minHeight: 132,
                  }}>
                    <div className="row-between" style={{ alignItems: "center" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{
                          width: 22, height: 22, borderRadius: 6,
                          background: p.color, color: "white",
                          display: "inline-flex", alignItems: "center", justifyContent: "center",
                          fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 9.5,
                        }}>{p.glyph}</span>
                        <span style={{ fontSize: 12, fontWeight: 700 }}>{p.name}</span>
                      </div>
                      {p.status === "ready"
                        ? <Icon name="check" size={12} style={{ color: "var(--green)" }}/>
                        : <span style={{ fontSize: 10, color: "var(--muted)", fontWeight: 600 }}>{t.pubInQueue}</span>}
                    </div>
                    <div style={{
                      fontSize: 10.5, color: "var(--muted)",
                      letterSpacing: "0.02em",
                      fontFamily: "var(--font-mono)",
                    }}>{p.rule}</div>
                    <div style={{
                      fontSize: 11.5, lineHeight: 1.45,
                      color: p.status === "ready" ? "var(--ink)" : "var(--muted-2)",
                      flex: 1,
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      fontStyle: p.status === "ready" ? "normal" : "italic",
                    }}>{p.preview}</div>
                    {p.status === "ready" && (
                      <div className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                        <button className="btn-link muted" style={{ fontSize: 11 }}>{t.editShort}</button>
                        <button className="btn-link muted" style={{ fontSize: 11 }}>
                          <Icon name="copy" size={10}/> копия
                        </button>
                      </div>
                    )}
                  </div>
                ))}
            </div>
          </div>
        )}

        {tab === "edit" && (
          <div>
            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenTrim(!openTrim)}>
                <span>{t.trimming} <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {t.trimmingHint}</span></span>
                <span className={"caret " + (openTrim ? "open" : "")}>›</span>
              </button>
              {openTrim && (
                <div className="collapse-body">
                  <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 10 }}>
                    Подвинь рамки start/end — получим новый клип за ~6 секунд (без транскрипции).
                  </div>
                  <Timeline clip={clip} />
                </div>
              )}
            </div>
            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenReframe(!openReframe)}>
                <span>Smart reframe <span style={{ color: "var(--muted)", fontWeight: 400 }}>· face/text/object</span></span>
                <span className={"caret " + (openReframe ? "open" : "")}>›</span>
              </button>
              {openReframe && (
                <div className="collapse-body">
                  <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
                    Реальные сегменты сцен из YOLOv8 + active-speaker-detection. Клик по сегменту → сменить layout.
                  </div>
                  <ReframeStrip clip={clip} />
                </div>
              )}
            </div>

            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenMusic(!openMusic)}>
                <span>{t.musicLabel} <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {t.musicHint}{clip.music?.track ? ` · ${clip.music.track}` : ""}</span></span>
                <span className={"caret " + (openMusic ? "open" : "")}>›</span>
              </button>
              {openMusic && <div className="collapse-body"><MusicPanel clip={clip}/></div>}
            </div>

            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenBroll(!openBroll)}>
                <span>B-roll <span style={{ color: "var(--muted)", fontWeight: 400 }}>· Pexels вставки в кадр</span></span>
                <span className={"caret " + (openBroll ? "open" : "")}>›</span>
              </button>
              {openBroll && <div className="collapse-body"><BrollPanel clip={clip}/></div>}
            </div>

            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenThumbs(!openThumbs)}>
                <span>{t.thumbsLabel} <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {t.thumbsHint}</span></span>
                <span className={"caret " + (openThumbs ? "open" : "")}>›</span>
              </button>
              {openThumbs && <div className="collapse-body"><ThumbnailsPanel clip={clip}/></div>}
            </div>

            <div>
              <label className="label">{t.subStyleForClip}</label>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 8 }}>
                {SUBTITLE_STYLES.map((s) => {
                  const isActive = clip.activeStyle === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => onChangeStyle(clip.id, s.id)}
                      style={{
                        cursor: "pointer",
                        border: isActive ? "2px solid var(--ink)" : "1px solid var(--line)",
                        borderRadius: 12,
                        padding: 10,
                        background: isActive ? "var(--bg-3)" : "var(--bg-2)",
                        boxShadow: isActive
                          ? "0 0 0 3px var(--lime), 0 6px 16px rgba(10,13,10,0.10)"
                          : "0 1px 0 rgba(255,255,255,0.6) inset",
                        display: "flex",
                        flexDirection: "column",
                        gap: 8,
                        textAlign: "left",
                      }}
                    >
                      {/* Live preview swatch */}
                      <div style={{
                        height: 44,
                        borderRadius: 8,
                        background: "linear-gradient(180deg, #2b2f36, #0e1014)",
                        position: "relative",
                        overflow: "hidden",
                        display: "flex", alignItems: "center", justifyContent: "center",
                      }}>
                        <span className={"sub-preview sub-" + s.id} style={{
                          fontSize: 11,
                          padding: "2px 6px",
                          letterSpacing: "0.01em",
                        }}>
                          {s.id === "karaoke" || s.id === "neon"
                            ? <>X10 <span className="hl">К</span></>
                            : "X10 К"}
                        </span>
                      </div>
                      <div className="row-between">
                        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink)" }}>{s.name}</span>
                        {isActive && (
                          <span style={{
                            width: 16, height: 16, borderRadius: 99,
                            background: "var(--lime)", color: "var(--ink)",
                            display: "inline-flex", alignItems: "center", justifyContent: "center",
                          }}>
                            <Icon name="check" size={10}/>
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {tab === "regen" && (
          <RegeneratePanel clip={clip} />
        )}

        {tab === "effects" && (
          <EffectsPanel clip={clip} />
        )}

        {tab === "publish" && (
          <div>
            <PublishGrid
              clip={clip}
              publishStatus={publishStatus}
              onPublish={onPublish}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ── RegeneratePanel — единая регенерация клипа со всеми настройками сразу ──
// Покрывает: trim (start/end), subtitle template, brand, cta, effects toggles, hook text.
// Бэкенд считает минимальную инвалидацию кеша → меняем только бренд → не пере-рендерим reframe.
function RegeneratePanel({ clip }) {
  const t = _i18n();
  const { Icon } = window.UI;

  // парсим текущий range "12.4s — 42.1s" из mock-обёртки → используем сырые start/end из state.json
  // clip.range содержит "MM:SS-MM:SS", clip.duration содержит "Xс" — этого мало.
  // Пробуем взять _start/_end если есть, иначе парсим range.
  const _initStart = clip._start != null ? clip._start : 0;
  const _initEnd = clip._end != null ? clip._end : 0;

  const [start, setStart] = React.useState(_initStart);
  const [end, setEnd] = React.useState(_initEnd);
  const [template, setTemplate] = React.useState(clip.activeStyle || "block");
  const [brand, setBrand] = React.useState(clip._brand || "excella");
  const [cta, setCta] = React.useState(clip._cta || "demo");
  const [effectsOn, setEffectsOn] = React.useState(!!clip.effects_applied);
  const [zoom, setZoom] = React.useState(true);
  const [emoji, setEmoji] = React.useState(true);
  const [hook, setHook] = React.useState(true);
  const [sfx, setSfx] = React.useState(false);
  const [hookText, setHookText] = React.useState("");

  const [brandsList, setBrandsList] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [okMsg, setOkMsg] = React.useState("");
  const [whatChanged, setWhatChanged] = React.useState(null);

  // подгрузить список брендов и их CTA-пресеты
  React.useEffect(() => {
    window.API.brands().then((bs) => setBrandsList(bs || [])).catch(() => {});
  }, []);

  React.useEffect(() => {
    setStart(_initStart);
    setEnd(_initEnd);
    setTemplate(clip.activeStyle || "block");
    setBrand(clip._brand || "excella");
    setCta(clip._cta || "demo");
    setEffectsOn(!!clip.effects_applied);
  }, [clip.id]);

  const SUBTITLE_STYLES = window.MOCK.SUBTITLE_STYLES || [];
  const activeBrand = brandsList.find((b) => b.name === brand);
  const ctaOptions = activeBrand?.cta_presets || [];

  const duration = Math.max(0, end - start);

  // оценка времени (что инвалидируется → как долго)
  const trimChanged = Math.abs(start - _initStart) > 0.05 || Math.abs(end - _initEnd) > 0.05;
  const tplChanged = template !== (clip.activeStyle || "block");
  const brandChanged = brand !== (clip._brand || "excella");
  const ctaChanged = cta !== (clip._cta || "demo");
  const effectsChanged = effectsOn !== !!clip.effects_applied || (effectsOn && (zoom || emoji || hook || sfx) && hookText);

  const estimate = trimChanged ? t.regenEstFull
                 : tplChanged ? t.regenEstSubs
                 : effectsChanged ? t.regenEstEffects
                 : (brandChanged || ctaChanged) ? t.regenEstBrand
                 : null;

  const apply = async () => {
    if (!clip._jobId) return;
    setBusy(true); setError(""); setOkMsg(""); setWhatChanged(null);
    try {
      const body = {};
      if (trimChanged) { body.start = start; body.end = end; }
      if (tplChanged) body.template = template;
      if (brandChanged) body.brand = brand;
      if (ctaChanged) body.cta = cta;

      // эффекты: всегда отправляем apply_effects если переключился on/off
      if (effectsOn !== !!clip.effects_applied) {
        body.apply_effects = effectsOn;
      }
      if (effectsOn) {
        body.enable_zoom = zoom;
        body.enable_emoji = emoji;
        body.enable_hook = hook;
        body.enable_sfx = sfx;
        if (hookText.trim()) body.hook_text_override = hookText.trim();
      }

      if (Object.keys(body).length === 0) {
        setError(t.regenChangedNothing);
        setBusy(false);
        return;
      }

      const res = await window.API.regenerateClip(
        clip._jobId, clip._index + 1, body,
      );
      const stages = res?.what_changed || [];
      setWhatChanged(stages);
      setOkMsg(t.regenDone);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const Section = ({ title, children }) => (
    <div style={{
      padding: 12, borderRadius: 12, background: "var(--bg-2)",
      border: "1px solid var(--line)", marginBottom: 10,
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--muted)",
                    letterSpacing: "0.04em", textTransform: "uppercase",
                    marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );

  const Toggle = ({ label, value, onChange, hint }) => (
    <label style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 10px", border: "1px solid var(--line)",
      borderRadius: 10, background: value ? "var(--bg-3)" : "var(--bg-2)",
      cursor: "pointer",
    }}>
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)}/>
      <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{label}</span>
        {hint && <span style={{ color: "var(--muted)", fontSize: 11 }}>{hint}</span>}
      </div>
    </label>
  );

  const stageBadge = (s) => {
    const map = {
      silent: t.regenStageTrim,
      preeffects: t.regenStageSubs,
      fx: t.regenStageFx,
      brand_master: t.regenStageBrand,
      effects_off: t.regenStageEffectsOff,
    };
    return map[s] || s;
  };

  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: 13, color: "var(--muted)" }}>
        {t.regenHeading}
      </div>

      {/* ── Trim ── */}
      <Section title={t.regenSectionTrim}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 10, alignItems: "end" }}>
          <div>
            <label className="label">{t.regenStart}</label>
            <input className="input mono" type="number" step="0.1" min={0}
                   value={start} onChange={(e) => setStart(+e.target.value)}/>
          </div>
          <div>
            <label className="label">{t.regenEnd}</label>
            <input className="input mono" type="number" step="0.1" min={start + 5}
                   value={end} onChange={(e) => setEnd(+e.target.value)}/>
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--muted)",
                        paddingBottom: 8 }}>
            {t.regenDuration}: <strong style={{ color: "var(--ink)" }}>{duration.toFixed(1)}с</strong>
          </div>
        </div>
      </Section>

      {/* ── Subtitle template ── */}
      <Section title={t.regenSectionTemplate}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))", gap: 8 }}>
          {SUBTITLE_STYLES.map((s) => {
            const isActive = template === s.id;
            return (
              <button
                key={s.id}
                onClick={() => setTemplate(s.id)}
                style={{
                  cursor: "pointer", padding: "8px 10px",
                  border: isActive ? "2px solid var(--ink)" : "1px solid var(--line)",
                  borderRadius: 10, background: isActive ? "var(--bg-3)" : "var(--bg-2)",
                  textAlign: "left", fontSize: 12, fontWeight: 700,
                }}
              >
                {s.name}
              </button>
            );
          })}
        </div>
      </Section>

      {/* ── Brand + CTA ── */}
      <Section title={t.regenSectionBrand}>
        <div className="grid-2" style={{ gap: 12 }}>
          <div>
            <label className="label">{t.regenBrandLabel}</label>
            <select className="input" value={brand} onChange={(e) => {
              setBrand(e.target.value);
              const newBrand = brandsList.find((b) => b.name === e.target.value);
              if (newBrand) setCta(newBrand.cta_default || (newBrand.cta_presets[0]?.key || "demo"));
            }}>
              {brandsList.length === 0 && <option value={brand}>{brand}</option>}
              {brandsList.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t.regenCtaLabel}</label>
            <select className="input" value={cta} onChange={(e) => setCta(e.target.value)}>
              {ctaOptions.length === 0 && <option value={cta}>{cta}</option>}
              {ctaOptions.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.key} — {(p.text || "").slice(0, 30)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Section>

      {/* ── Effects ── */}
      <Section title={t.regenSectionEffects}>
        <div style={{ marginBottom: effectsOn ? 10 : 0 }}>
          <Toggle label={t.regenEffectsOn} hint={t.regenEffectsOnHint}
                  value={effectsOn} onChange={setEffectsOn}/>
        </div>
        {effectsOn && (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
              <Toggle label={t.effectsZoom} hint={t.effectsZoomHint}
                      value={zoom} onChange={setZoom}/>
              <Toggle label={t.effectsEmoji} hint={t.effectsEmojiHint}
                      value={emoji} onChange={setEmoji}/>
              <Toggle label={t.effectsHook} hint={t.effectsHookHint}
                      value={hook} onChange={setHook}/>
              <Toggle label={t.effectsSfx}
                      hint={sfx ? t.effectsSfxHintOn : t.effectsSfxHintOff}
                      value={sfx} onChange={setSfx}/>
            </div>
            {hook && (
              <div>
                <label className="label" style={{ marginBottom: 4, display: "block" }}>
                  {t.effectsHookText} <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {t.effectsHookOptional}</span>
                </label>
                <input className="input" placeholder={t.effectsHookPlaceholder}
                       value={hookText} onChange={(e) => setHookText(e.target.value)}
                       maxLength={60}/>
              </div>
            )}
          </div>
        )}
      </Section>

      {/* ── Apply ── */}
      <div className="row" style={{ gap: 12, alignItems: "center" }}>
        <button className="btn primary" disabled={busy} onClick={apply}
                style={{ minWidth: 220 }}>
          <Icon name="sparkles" size={13}/> {busy ? t.regenApplying : t.regenApply}
        </button>
        {estimate && !busy && (
          <span style={{ color: "var(--muted)", fontSize: 12 }}>{estimate}</span>
        )}
      </div>

      {error && (
        <div style={{ marginTop: 10, color: "var(--danger)", fontSize: 13 }}>
          {t.regenError} {error}
        </div>
      )}
      {okMsg && !error && (
        <div style={{ marginTop: 10, fontSize: 13, color: "var(--green)" }}>
          {okMsg}
          {whatChanged && whatChanged.length > 0 && (
            <span style={{ color: "var(--muted)", marginLeft: 8 }}>
              {t.regenChanged} {whatChanged.map(stageBadge).join(", ")}
            </span>
          )}
        </div>
      )}
    </div>
  );
}


// ── EffectsPanel — тогглы и регенерация zoom / emoji / hook / sfx ──
function EffectsPanel({ clip }) {
  const t = _i18n();
  const applied = clip.effects_applied || null;
  const [zoom,  setZoom ] = React.useState(true);
  const [emoji, setEmoji] = React.useState(true);
  const [hook,  setHook ] = React.useState(true);
  const [sfx,   setSfx  ] = React.useState(false);
  const [hookText, setHookText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [okMsg, setOkMsg] = React.useState("");

  const regenerate = async () => {
    setBusy(true); setError(""); setOkMsg("");
    try {
      const body = {
        enable_zoom: zoom,
        enable_emoji: emoji,
        enable_hook: hook,
        enable_sfx: sfx,
      };
      if (hookText.trim()) body.hook_text_override = hookText.trim();
      const res = await window.API.regenerateEffects(
        clip._jobId, clip._index + 1, body,
      );
      const a = res.plan || {};
      setOkMsg(
        `${t.effectsResultDone} · zoom: ${(a.accents || []).length} · ` +
        `emoji: ${(a.emojis || []).length} · ` +
        `sfx: ${(a.sfx || []).length} · ` +
        `hook: ${a.hook ? "+" : "-"}`
      );
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const Toggle = ({ label, value, onChange, hint }) => (
    <label style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 12px", border: "1px solid var(--line)",
      borderRadius: 10, background: value ? "var(--bg-3)" : "var(--bg-2)",
      cursor: "pointer",
    }}>
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)}/>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{label}</span>
        {hint && <span style={{ color: "var(--muted)", fontSize: 11 }}>{hint}</span>}
      </div>
    </label>
  );

  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: 13, color: "var(--muted)" }}>
        {t.effectsHeading}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        <Toggle label={t.effectsZoom}
                hint={t.effectsZoomHint}
                value={zoom}  onChange={setZoom}/>
        <Toggle label={t.effectsEmoji}
                hint={t.effectsEmojiHint}
                value={emoji} onChange={setEmoji}/>
        <Toggle label={t.effectsHook}
                hint={t.effectsHookHint}
                value={hook}  onChange={setHook}/>
        <Toggle label={t.effectsSfx}
                hint={sfx ? t.effectsSfxHintOn : t.effectsSfxHintOff}
                value={sfx}   onChange={setSfx}/>
      </div>

      {hook && (
        <div style={{ marginBottom: 12 }}>
          <label className="label" style={{ marginBottom: 4, display: "block" }}>
            {t.effectsHookText} <span style={{ color: "var(--muted)", fontWeight: 400 }}>· {t.effectsHookOptional}</span>
          </label>
          <input className="input" placeholder={t.effectsHookPlaceholder}
                 value={hookText} onChange={(e) => setHookText(e.target.value)}
                 maxLength={60}/>
        </div>
      )}

      {applied && (
        <div style={{
          fontSize: 12, color: "var(--muted)", marginBottom: 10,
          padding: 8, border: "1px solid var(--line)", borderRadius: 8,
        }}>
          {t.effectsAppliedLast}
          {" "}zoom={applied.accents}, emoji={applied.emojis}, sfx={applied.sfx}
          {applied.hook ? `, hook="${applied.hook}"` : `, ${t.effectsNoHook}`}
        </div>
      )}

      <button className="btn primary" disabled={busy} onClick={regenerate}
              style={{ minWidth: 200 }}>
        {busy ? t.effectsApplying : t.effectsApply}
      </button>

      {error && (
        <div style={{ marginTop: 10, color: "var(--danger)", fontSize: 13 }}>
          {t.effectsError} {error}
        </div>
      )}
      {okMsg && !error && (
        <div style={{ marginTop: 10, color: "var(--green)", fontSize: 13 }}>
          {okMsg}
        </div>
      )}
    </div>
  );
}


function PosterCaption({ clip, style }) {
  // Live caption preview overlay on poster
  const cls =
    style.id === "karaoke" ? "sub-karaoke" :
    style.id === "block" ? "sub-block" :
    style.id === "minimal" ? "sub-minimal" :
    style.id === "neon" ? "sub-neon" :
    style.id === "telegram" ? "sub-telegram" :
    style.id === "bigwhite" ? "sub-bigwhite" : "sub-block";
  const word = clip.n === 1 ? "СДЕЛКЕ" : clip.n === 2 ? "ЛПРа" : clip.n === 3 ? "ВОРОНКА" : clip.n === 4 ? "БЫСТРО" : "МИЛЛИОН";
  return (
    <div className="poster-cap">
      {style.id === "karaoke" || style.id === "neon" ? (
        <span className={"sub-preview " + cls}>X10 К <span className="hl">{word}</span></span>
      ) : style.id === "minimal" ? (
        <span className={"sub-preview " + cls}>{word.toLowerCase()}</span>
      ) : (
        <span className={"sub-preview " + cls}>{word}</span>
      )}
    </div>
  );
}

// ── Publish grid: реальные статусы подключения и публикации per-platform ──
function PublishGrid({ clip, publishStatus, onPublish }) {
  const t = _i18n();
  const platforms = [
    { id: "instagram", name: t.pubInstagramName, hint: t.pubInstagramHint },
    { id: "vk",        name: t.pubVkName,        hint: t.pubVkHint },
    { id: "youtube",   name: t.pubYoutubeName,   hint: t.pubYoutubeHint },
    { id: "tiktok",    name: t.pubTiktokName,    hint: t.pubTiktokHint },
  ];
  return (
    <div className="grid-2">
      {platforms.map((p) => {
        const st = publishStatus?.[p.id] || {};
        const connected = !!st.connected;
        const pub = (clip.publications || {})[p.id];   // если уже опубликовано — есть {url, video_id}
        const isManual = p.id === "tiktok";
        return (
          <PublishCard
            key={p.id}
            name={p.name}
            connected={connected}
            isManual={isManual}
            published={pub}
            hint={isManual ? t.pubTiktokFolderHint : p.hint}
            onPublish={() => onPublish(clip, p.id)}
            disabled={!clip._jobId || (!connected && !isManual)}
          />
        );
      })}
    </div>
  );
}

function PublishCard({ name, connected, isManual, published, hint, onPublish, disabled }) {
  const t = _i18n();
  const { Icon } = window.UI;
  const badge = published
    ? <span className="badge-ok">{t.pubStatusPublished}</span>
    : isManual
      ? <span className="chip" style={{ fontSize: 11, padding: "3px 8px" }}>{t.pubManualBadge}</span>
      : connected
        ? <span className="badge-ok">{t.pubStatusConnected}</span>
        : <span className="badge-warn">{t.pubStatusNotConnected}</span>;
  return (
    <div style={{ padding: 16, border: "1px solid var(--line)", borderRadius: 14, background: "var(--bg-3)" }}>
      <div className="row-between">
        <div style={{ fontWeight: 700, fontSize: 14 }}>{name}</div>
        {badge}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 6, lineHeight: 1.5 }}>{hint}</div>
      {published?.url && (
        <a
          href={published.url} target="_blank" rel="noreferrer"
          className="btn-link"
          style={{ display: "inline-flex", marginTop: 8, fontSize: 12, gap: 4, alignItems: "center" }}
        >
          → {published.url.length > 40 ? published.url.slice(0, 40) + "…" : published.url}
        </a>
      )}
      <button
        className="btn btn-primary"
        style={{ width: "100%", justifyContent: "center", marginTop: 12 }}
        onClick={onPublish}
        disabled={disabled}
      >
        <Icon name="send" size={14}/> {published ? t.pubReupload : t.pubPublishBtn}
      </button>
    </div>
  );
}

function Timeline({ clip }) {
  // Simple visual: waveform bars + start/end handles
  const bars = React.useMemo(() => Array.from({ length: 80 }, (_, i) => 0.25 + Math.abs(Math.sin(i * 0.6 + clip.id)) * 0.7), [clip.id]);
  const [start, setStart] = React.useState(8);
  const [end, setEnd] = React.useState(70);
  return (
    <div>
      <div style={{ position: "relative", height: 64, padding: "0 6px", display: "flex", alignItems: "flex-end", gap: 2, background: "var(--bg-2)", borderRadius: 10, border: "1px solid var(--line-2)", overflow: "hidden" }}>
        {bars.map((h, i) => {
          const inside = i >= start && i <= end;
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: `${h * 100}%`,
                background: inside ? "var(--ink)" : "rgba(10,13,10,0.18)",
                borderRadius: 1,
              }}
            />
          );
        })}
        <div style={{ position: "absolute", left: `${(start / 80) * 100}%`, top: 0, bottom: 0, width: 3, background: "var(--lime-2)", borderRadius: 99 }}></div>
        <div style={{ position: "absolute", left: `${(end / 80) * 100}%`, top: 0, bottom: 0, width: 3, background: "var(--lime-2)", borderRadius: 99 }}></div>
      </div>
      <div className="row-between" style={{ marginTop: 12, fontSize: 12, color: "var(--muted)" }}>
        <span className="mono">start: 0:{(start * 0.6).toFixed(1).padStart(4, "0")}</span>
        <div className="row" style={{ gap: 8 }}>
          <input type="range" min={0} max={end - 5} value={start} onChange={(e) => setStart(+e.target.value)} style={{ width: 100 }}/>
          <input type="range" min={start + 5} max={80} value={end} onChange={(e) => setEnd(+e.target.value)} style={{ width: 100 }}/>
        </div>
        <span className="mono">end: 0:{(end * 0.6).toFixed(1).padStart(4, "0")}</span>
      </div>
      <button className="btn btn-primary" style={{ marginTop: 12 }}>
        Применить и пере-рендерить (~6с)
      </button>
    </div>
  );
}

// ── ReframeStrip — реальные сегменты сцен из /jobs/{j}/clips/{i}/scenes ──
function ReframeStrip({ clip }) {
  const { Icon } = window.UI;
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!clip?._jobId || clip?._index == null) return;
    let cancelled = false;
    window.API.jobScenes(clip._jobId, clip._index + 1)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message || String(e)); });
    return () => { cancelled = true; };
  }, [clip?._jobId, clip?._index]);

  if (error) {
    // например "сцены не найдены — нужен повторный прогон"
    return (
      <div className="hint" style={{ background: "rgba(224,74,63,0.08)", borderColor: "rgba(224,74,63,0.3)" }}>
        Не удалось загрузить сегменты: {error}
      </div>
    );
  }
  if (!data) {
    return <div style={{ fontSize: 12, color: "var(--muted)" }}>{_i18n().loadingSegments}</div>;
  }

  const segments = data.segments || [];
  const total = data.clip_duration || 1;

  // Цвета по layout — синий = лицо/спикер, янтарный = экран, зелёный = группа/обзорный
  const layoutColor = (layout) => {
    if (!layout) return "linear-gradient(180deg, #888, #444)";
    if (layout.includes("speaker") || layout === "active_speaker_close")
      return "linear-gradient(180deg, #5a7a8d, #2c3e50)";
    if (layout.includes("screen"))
      return "linear-gradient(180deg, #f5e6c8, #c89b6a)";
    if (layout.includes("wide") || layout === "wide_group")
      return "linear-gradient(180deg, #6a8d5a, #2e3e2c)";
    if (layout === "split_screen")
      return "linear-gradient(135deg, #5a7a8d 50%, #c89b6a 50%)";
    return "linear-gradient(180deg, #888, #444)";
  };

  return (
    <div>
      {segments.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Для этого клипа не сохранены сегменты сцен.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 4, height: 80, alignItems: "stretch" }}>
          {segments.map((s, i) => {
            const w = Math.max(2, ((s.end - s.start) / total) * 100);
            return (
              <div
                key={i}
                title={`${s.layout} · ${s.start.toFixed(1)}–${s.end.toFixed(1)}с${s.overridden ? " · ✎" : ""}`}
                style={{
                  flex: `${w} 1 0`, minWidth: 18,
                  background: layoutColor(s.layout),
                  borderRadius: 8,
                  position: "relative",
                  border: s.overridden ? "2px solid var(--lime)" : "1px solid var(--line)",
                  cursor: "pointer",
                }}
              >
                <span style={{
                  position: "absolute", left: 4, top: 4,
                  background: "rgba(0,0,0,0.6)", color: "white",
                  fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 99,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  maxWidth: "calc(100% - 8px)",
                }}>{s.layout}</span>
                <span style={{
                  position: "absolute", right: 4, bottom: 4,
                  background: "var(--lime)", color: "var(--ink)",
                  fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 99,
                }}>{s.end.toFixed(0)}с</span>
              </div>
            );
          })}
        </div>
      )}
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
        {segments.length} сегментов · {(data.available_face_ids || []).length} лиц распознано · клип {data.clip_duration?.toFixed(1)}с
      </div>
    </div>
  );
}

// ── UniquifyPanel — реальная генерация per-platform через /uniquify ──
const _UNIQ_PLATFORMS = [
  { id: "instagram", name: "Instagram", glyph: "IG",
    color: "linear-gradient(135deg, #f58529, #dd2a7b, #8134af)",
    rule: "≤125 знаков · 30 #тегов в 1-й коммент" },
  { id: "vk", name: _i18n().pubVkName, glyph: "VK",
    color: "linear-gradient(135deg, #4a76a8, #2d5b8b)",
    rule: _i18n().pubLongFormatRule },
  { id: "youtube", name: "Shorts", glyph: "YT",
    color: "linear-gradient(135deg, #ff0033, #c4001a)",
    rule: "≤60 знаков · хук в начале · 3 #тега" },
  { id: "tiktok", name: "TikTok", glyph: "TT",
    color: "linear-gradient(135deg, #25F4EE, #FE2C55)",
    rule: "≤150 знаков · trend-теги · хук" },
];

function UniquifyPanel({ clip, t, Icon }) {
  // state per-platform: "idle" | "running" | "ready" | "error"
  const [statuses, setStatuses] = React.useState(() =>
    Object.fromEntries(_UNIQ_PLATFORMS.map((p) => [p.id, "idle"]))
  );
  const [errors, setErrors] = React.useState({});

  const runOne = async (platId) => {
    if (!clip._jobId) return;
    setStatuses((s) => ({ ...s, [platId]: "running" }));
    setErrors((e) => ({ ...e, [platId]: "" }));
    try {
      await window.API.uniquifyClip(clip._jobId, clip._index + 1, {
        platform: platId, save_as_alt: true,
      });
      setStatuses((s) => ({ ...s, [platId]: "ready" }));
    } catch (err) {
      setStatuses((s) => ({ ...s, [platId]: "error" }));
      setErrors((e) => ({ ...e, [platId]: err.message || String(err) }));
    }
  };

  const runAll = async () => {
    for (const p of _UNIQ_PLATFORMS) {
      // последовательно — чтобы не нагружать ffmpeg одновременно
      // eslint-disable-next-line no-await-in-loop
      await runOne(p.id);
    }
  };

  const anyRunning = Object.values(statuses).some((s) => s === "running");

  return (
    <div className="cta-preset" style={{ background: "var(--bg-2)", padding: 16 }}>
      <div className="row-between" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            width: 28, height: 28, borderRadius: 8,
            background: "var(--lime)", color: "var(--ink)",
            display: "inline-flex", alignItems: "center", justifyContent: "center",
          }}>
            <Icon name="sparkles" size={14}/>
          </span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{t.uniqueByPlatform}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 1 }}>
              мастер → пер-платформенные варианты (re-encode под алгоритмы)
            </div>
          </div>
        </div>
        <button
          className="btn btn-primary"
          style={{ padding: "8px 14px", fontSize: 13 }}
          onClick={runAll}
          disabled={anyRunning || !clip._jobId}
        >
          <Icon name="sparkles" size={13}/> {anyRunning ? t.generating : t.generateAll}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
        {_UNIQ_PLATFORMS.map((p) => {
          const st = statuses[p.id];
          const err = errors[p.id];
          const isRunning = st === "running";
          const isReady = st === "ready";
          const isErr = st === "error";
          return (
            <div key={p.id} style={{
              padding: 12, borderRadius: 12, background: "var(--bg-3)",
              border: isReady ? "1px solid rgba(46,160,82,0.45)" : "1px solid var(--line)",
              display: "flex", flexDirection: "column", gap: 8, minHeight: 120,
            }}>
              <div className="row-between" style={{ alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 6,
                    background: p.color, color: "white",
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 9.5,
                  }}>{p.glyph}</span>
                  <span style={{ fontSize: 12, fontWeight: 700 }}>{p.name}</span>
                </div>
                {isReady && <span className="badge-ok">{t.statusReadyShort}</span>}
                {isRunning && <span className="badge-warn" style={{ background: "rgba(198,255,61,0.2)", color: "var(--ink)" }}>{t.generating}</span>}
                {isErr && <span className="badge-warn">{t.statusError}</span>}
              </div>
              <div style={{
                fontSize: 10.5, color: "var(--muted)",
                fontFamily: "var(--font-mono)",
              }}>{p.rule}</div>
              {isErr && err && (
                <div style={{ fontSize: 11, color: "var(--danger)", lineHeight: 1.4 }}>
                  {err.length > 80 ? err.slice(0, 80) + "…" : err}
                </div>
              )}
              <div className="row" style={{ gap: 6, justifyContent: "flex-end", marginTop: "auto" }}>
                <button
                  className="btn-link muted"
                  style={{ fontSize: 11 }}
                  disabled={isRunning || !clip._jobId}
                  onClick={() => runOne(p.id)}
                >
                  {isReady ? t.regenerate : isErr ? t.retry : t.generate}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// MusicPanel — /audio-library + add-music
// ─────────────────────────────────────────────────────────────────
function MusicPanel({ clip }) {
  const t = _i18n();
  const { Icon } = window.UI;
  const [library, setLibrary] = React.useState([]);
  const [selected, setSelected] = React.useState(clip.music?.track || "");
  const [volume, setVolume] = React.useState(clip.music?.volume ?? 0.15);
  const [duck, setDuck] = React.useState(clip.music?.duck ?? true);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const fileRef = React.useRef(null);

  const reload = React.useCallback(() => {
    window.API.audioLibrary().then(setLibrary).catch((e) => setError(e.message));
  }, []);
  React.useEffect(() => { reload(); }, [reload]);

  const upload = async (file) => {
    if (!file) return;
    setBusy("upload");
    try {
      await window.API.uploadAudio(file);
      await reload();
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  };

  const removeTrack = async (name) => {
    if (!confirm(`Удалить трек ${name} из библиотеки?`)) return;
    try {
      await window.API.deleteAudio(name);
      await reload();
      if (selected === name) setSelected("");
    } catch (e) { setError(e.message); }
  };

  const apply = async () => {
    if (!selected || !clip._jobId) return;
    setBusy("apply"); setError("");
    try {
      await window.API.addMusic(clip._jobId, clip._index + 1, {
        track: selected, volume: Number(volume), duck,
      });
      alert(`Музыка «${selected}» добавлена в клип`);
    } catch (e) { setError(e.message); }
    finally { setBusy(""); }
  };

  return (
    <div>
      {error && <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <div className="row-between" style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Библиотека треков · {library.length} шт
        </div>
        <input ref={fileRef} type="file" hidden accept="audio/*,.mp3,.m4a,.wav,.ogg" onChange={(e) => upload(e.target.files[0])}/>
        <button className="btn btn-ghost" onClick={() => fileRef.current?.click()} disabled={busy === "upload"}>
          <Icon name="upload" size={13}/> {busy === "upload" ? t.uploading : t.uploadTrack}
        </button>
      </div>

      {library.length === 0 ? (
        <div className="hint">
          Библиотека пуста. Загрузи MP3/WAV — он появится здесь и для всех будущих клипов.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 220, overflowY: "auto", marginBottom: 12 }}>
          {library.map((tr) => (
            <button
              key={tr.name}
              onClick={() => setSelected(tr.name)}
              style={{
                display: "grid", gridTemplateColumns: "auto 1fr auto auto", gap: 10, alignItems: "center",
                padding: "8px 12px", borderRadius: 10,
                border: selected === tr.name ? "2px solid var(--lime-2)" : "1px solid var(--line)",
                background: selected === tr.name ? "rgba(198,255,61,0.10)" : "var(--bg-3)",
                cursor: "pointer", textAlign: "left",
              }}
            >
              <span style={{ width: 28, height: 28, borderRadius: 8, background: "var(--ink)", color: "var(--lime)", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                <Icon name="play" size={11}/>
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {tr.name}
              </span>
              <span style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>{tr.size_kb} KB</span>
              <span
                role="button"
                onClick={(e) => { e.stopPropagation(); removeTrack(tr.name); }}
                style={{ fontSize: 11, color: "var(--danger)", fontWeight: 600, cursor: "pointer" }}
              >{t.deleteShort}</span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="grid-3" style={{ alignItems: "end", gap: 14, marginTop: 6 }}>
          <div>
            <label className="label">Громкость музыки · {Math.round(volume * 100)}%</label>
            <input
              type="range" min={0} max={1} step={0.05}
              value={volume} onChange={(e) => setVolume(+e.target.value)}
              style={{ width: "100%" }}
            />
          </div>
          <label className="switch">
            <span>Duck (приглушать на голосе)</span>
            <input type="checkbox" checked={duck} onChange={(e) => setDuck(e.target.checked)}/>
            <span className="track"></span>
          </label>
          <button className="btn btn-primary" onClick={apply} disabled={busy === "apply" || !clip._jobId}>
            {busy === "apply" ? t.mounting : `${t.apply} «${selected.length > 22 ? selected.slice(0, 22) + "…" : selected}»`}
          </button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// BrollPanel — поиск Pexels + вставка
// ─────────────────────────────────────────────────────────────────
function BrollPanel({ clip }) {
  const t = _i18n();
  const { Icon } = window.UI;
  const [keyword, setKeyword] = React.useState("");
  const [results, setResults] = React.useState([]);
  const [searching, setSearching] = React.useState(false);
  const [error, setError] = React.useState("");
  const [selected, setSelected] = React.useState(null);
  const [insertAt, setInsertAt] = React.useState(0);
  const [duration, setDuration] = React.useState(2);
  const [applying, setApplying] = React.useState(false);

  const search = async () => {
    if (!keyword) return;
    setSearching(true); setError(""); setResults([]);
    try {
      const r = await window.API.brollSearch({ keyword, per_page: 6 });
      setResults(r);
    } catch (e) { setError(e.message); }
    finally { setSearching(false); }
  };

  const apply = async () => {
    if (!selected || !clip._jobId) return;
    setApplying(true); setError("");
    try {
      await window.API.addBroll(clip._jobId, clip._index + 1, {
        pexels_url: selected.url || selected.video_url || selected.preview_url,
        insert_at: Number(insertAt),
        duration: Number(duration),
      });
      alert("B-roll вставлен");
      setSelected(null);
    } catch (e) { setError(e.message); }
    finally { setApplying(false); }
  };

  return (
    <div>
      {error && <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <div className="row" style={{ gap: 8, marginBottom: 12 }}>
        <input
          className="input"
          placeholder={t.pexelsSearchPlaceholder}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          style={{ flex: 1 }}
        />
        <button className="btn btn-primary" onClick={search} disabled={searching || !keyword}>
          <Icon name="sparkles" size={13}/> {searching ? t.searching : t.find}
        </button>
      </div>

      {!keyword && results.length === 0 && (
        <div className="hint">
          Нужен <strong>PEXELS_API_KEY</strong> в Настройки → Pexels API. Бесплатно, 200 запросов/час.
        </div>
      )}

      {results.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8, marginBottom: 14 }}>
          {results.map((r, i) => {
            const isSel = selected === r;
            return (
              <button key={i} onClick={() => setSelected(r)} style={{
                cursor: "pointer", padding: 0, borderRadius: 10, overflow: "hidden",
                border: isSel ? "2px solid var(--lime-2)" : "1px solid var(--line)",
                boxShadow: isSel ? "0 0 0 3px rgba(198,255,61,0.35)" : "none",
                background: "var(--bg-3)",
              }}>
                {r.preview_image && (
                  <img src={r.preview_image} alt="" style={{ display: "block", width: "100%", aspectRatio: "16/9", objectFit: "cover" }}/>
                )}
                <div style={{ padding: "6px 8px", textAlign: "left" }}>
                  <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>
                    {r.duration ? `${r.duration}с` : ""} · {r.user || "pexels"}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {selected && (
        <div className="cta-preset" style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 12, alignItems: "end" }}>
          <div>
            <label className="label">{t.insertAtSec}</label>
            <input className="input mono" type="number" step="0.5" value={insertAt} onChange={(e) => setInsertAt(+e.target.value)}/>
          </div>
          <div>
            <label className="label">{t.durationSec}</label>
            <input className="input mono" type="number" step="0.5" value={duration} onChange={(e) => setDuration(+e.target.value)}/>
          </div>
          <button className="btn btn-primary" onClick={apply} disabled={applying || !clip._jobId}>
            {applying ? t.mounting : t.insertBroll}
          </button>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// ThumbnailsPanel — POST /thumbnails/generate
// ─────────────────────────────────────────────────────────────────
function ThumbnailsPanel({ clip }) {
  const t = _i18n();
  const { Icon } = window.UI;
  const [thumbs, setThumbs] = React.useState(clip.thumbnails || []);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const generate = async () => {
    if (!clip._jobId) return;
    setBusy(true); setError("");
    try {
      const r = await window.API.generateThumbnails(clip._jobId, clip._index + 1);
      setThumbs(r?.thumbnails || []);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div>
      {error && <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <div className="row-between" style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Извлекает 3 кандидата-кадра для обложки. Выбери лучший — он подставится в публикации.
        </div>
        <button className="btn btn-primary" onClick={generate} disabled={busy || !clip._jobId}>
          <Icon name="sparkles" size={13}/> {busy ? t.generating : (thumbs.length ? t.regenerate : t.generate)}
        </button>
      </div>

      {thumbs.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
          {thumbs.map((rel, i) => (
            <div key={i} style={{ borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)" }}>
              <img
                src={window.API.thumbUrl(clip._jobId, rel.replace(/^thumbs\//, ""))}
                alt={`thumb ${i + 1}`}
                style={{ display: "block", width: "100%", aspectRatio: "9/16", objectFit: "cover", background: "#000" }}
              />
              <div style={{ padding: "6px 8px", fontSize: 11, color: "var(--muted)", fontFamily: "var(--font-mono)", textAlign: "center" }}>
                #{i + 1}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="hint">
          Нет извлечённых превью. Нажми «сгенерировать» — ffmpeg сделает 3 кадра из мастера.
        </div>
      )}
    </div>
  );
}

window.PROGRESSCLIPS = { ProgressBlock, RecentJobs, ClipCard };
