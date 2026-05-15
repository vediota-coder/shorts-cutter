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
  // ⭐ сортировка: newest|oldest|clips_desc|clips_asc|title
  const [sortBy, setSortBy] = React.useState(() => localStorage.getItem("recentJobsSort") || "newest");
  const { Icon } = window.UI;

  // подхватываем обновления MOCK.RECENT_JOBS из app.jsx (после нарезки)
  React.useEffect(() => {
    setList(window.MOCK.RECENT_JOBS || []);
  }, [window.MOCK.RECENT_JOBS]);

  // применяем сортировку, не мутируя оригинал
  const sortedList = React.useMemo(() => {
    const arr = [...list];
    if (sortBy === "newest") arr.sort((a, b) => (b._createdAt || 0) - (a._createdAt || 0));
    else if (sortBy === "oldest") arr.sort((a, b) => (a._createdAt || 0) - (b._createdAt || 0));
    else if (sortBy === "clips_desc") arr.sort((a, b) => (b.count || 0) - (a.count || 0));
    else if (sortBy === "clips_asc") arr.sort((a, b) => (a.count || 0) - (b.count || 0));
    else if (sortBy === "title") arr.sort((a, b) => (a.title || "").localeCompare(b.title || ""));
    return arr;
  }, [list, sortBy]);

  const changeSort = (v) => {
    setSortBy(v);
    try { localStorage.setItem("recentJobsSort", v); } catch {}
  };

  // короткая «когда» подпись типа «5 мин назад» / «вчера» / «12 мая»
  const formatWhen = (ts) => {
    if (!ts) return "";
    const now = Date.now() / 1000;
    const diff = now - ts;
    if (diff < 60) return "только что";
    if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
    if (diff < 2 * 86400) return "вчера";
    if (diff < 7 * 86400) return `${Math.floor(diff / 86400)} дн назад`;
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
  };

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
        _createdAt: it.created_at || 0,
      }));
      window.MOCK.RECENT_JOBS = mapped;
      setList(mapped);
      onDeleted?.();
    } catch (err) {
      alert(`Не удалилось: ${err.message}`);
    } finally { setBusyId(""); }
  };

  // ⭐ Перезапуск упавшего job-а: создаёт новый job_id с той же source_url,
  // старый удаляется. Полезно когда упали на pick/meta из-за временной ошибки API.
  const retryJob = async (e, j) => {
    e.stopPropagation();
    if (!j._id) return;
    setBusyId(j._id);
    try {
      const r = await window.API.retryJob(j._id);
      const fresh = await window.API.jobs(30);
      const mapped = fresh.map((it) => ({
        title: it.title || it.source_url || it.id,
        count: it.n_clips || 0,
        _id: it.id, _status: it.status, _stage: it.stage, _error: it.error,
        _createdAt: it.created_at || 0,
      }));
      window.MOCK.RECENT_JOBS = mapped;
      setList(mapped);
      onDeleted?.();  // refresh
    } catch (err) {
      alert(`Не перезапустилось: ${err.message}`);
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
      <div className="section-h" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h3 style={{ margin: 0 }}>{t.recentJobs}</h3>
        <span className="meta">{list.length} · сохранено локально</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <label style={{ fontSize: 12, color: "var(--muted)" }}>Сортировка:</label>
          <select
            value={sortBy}
            onChange={(e) => changeSort(e.target.value)}
            style={{
              fontSize: 13, padding: "5px 8px",
              border: "1px solid var(--line)", borderRadius: 8,
              background: "var(--bg-2)", color: "var(--ink)",
              cursor: "pointer",
            }}
          >
            <option value="newest">Сначала новые</option>
            <option value="oldest">Сначала старые</option>
            <option value="clips_desc">Больше клипов</option>
            <option value="clips_asc">Меньше клипов</option>
            <option value="title">По названию</option>
          </select>
        </div>
      </div>
      {list.length === 0 ? (
        <div className="hint">
          Заданий пока нет. Вставь YouTube-ссылку выше и нажми «Нарезать» — здесь появится первый.
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 10 }}>
          {sortedList.map((j) => {
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
                  <div className="row" style={{ gap: 8, marginBottom: 4, alignItems: "center" }}>
                    {badge && (
                      badge.cls === "chip"
                        ? <span className="chip" style={badge.style}>{badge.text}</span>
                        : <span className={badge.cls} style={badge.style}>{badge.text}</span>
                    )}
                    {j._createdAt ? (
                      <span style={{ fontSize: 11, color: "var(--muted)" }} title={new Date(j._createdAt * 1000).toLocaleString("ru-RU")}>
                        {formatWhen(j._createdAt)}
                      </span>
                    ) : null}
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
                  {/* ⭐ Кнопка retry — только для упавших job-ов с source_url */}
                  {j._status === "error" && (
                    <button
                      className="icon-btn"
                      title="Перезапустить (создать новый job с той же ссылкой)"
                      onClick={(e) => retryJob(e, j)}
                      disabled={isBusy}
                      style={{
                        width: 28, height: 28,
                        background: "var(--lime)", color: "var(--ink)",
                        borderColor: "var(--lime)",
                      }}
                    >
                      <Icon name="refresh" size={12}/>
                    </button>
                  )}
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

// WYSIWYG overlay субтитров поверх video-плеера в стиле Vizard.
// - Дефолт: рендер чанка по timeupdate, без взаимодействия.
// - Click по overlay → selected: рамка + 4 угловых handle'а.
//   * Drag по телу overlay → меняет margin_v (px от низа)
//   * Drag по угловому handle → меняет font size пропорционально
// - Изменения мгновенно применяются в overlay через локальные overrides,
//   PATCH /sub-overrides идёт debounced 220 ms.
// - Click вне overlay или Esc → deselect.
function SubtitleOverlay({ clip, videoRef, posterRef, targetH = 1056, enabled = true, styleVersion = 0, onLocalEdit }) {
  const [style, setStyle] = React.useState(null);
  const [words, setWords] = React.useState([]);
  const [activeIdx, setActiveIdx] = React.useState(-1);
  const [selected, setSelected] = React.useState(false);
  // local optimistic overrides (margin_v, size). Применяются в overlay немедленно,
  // PATCH идёт debounced.
  const [localOverrides, setLocalOverrides] = React.useState({});
  const dragState = React.useRef(null);  // {mode: 'move'|'resize-NW|NE|SW|SE', startY, startSize, startMargin, scale, videoH}
  const patchTimer = React.useRef(null);
  // ⭐ ref на актуальный clip — иначе useEffect([]) захватывает stale closure
  const clipRef = React.useRef(clip);
  React.useEffect(() => { clipRef.current = clip; }, [clip]);
  const onLocalEditRef = React.useRef(onLocalEdit);
  React.useEffect(() => { onLocalEditRef.current = onLocalEdit; }, [onLocalEdit]);

  React.useEffect(() => {
    if (!enabled || !clip._jobId || clip.n == null) return;
    let cancel = false;
    window.API.jobClipSubStyle(clip._jobId, clip.n, targetH)
      .then((s) => { if (!cancel) { setStyle(s); setLocalOverrides({}); } })
      .catch(() => { if (!cancel) setStyle(null); });
    return () => { cancel = true; };
  }, [clip._jobId, clip.n, targetH, enabled, styleVersion]);

  React.useEffect(() => {
    if (!enabled || !clip._jobId || clip.n == null) { setWords([]); return; }
    let cancel = false;
    window.API.jobClipWords(clip._jobId, clip.n)
      .then((d) => { if (!cancel) setWords(d?.words || []); })
      .catch(() => { if (!cancel) setWords([]); });
    return () => { cancel = true; };
  }, [clip._jobId, clip.n, enabled]);

  React.useEffect(() => {
    if (!enabled) return;
    const v = videoRef.current;
    if (!v) return;
    let raf = 0;
    const tick = () => {
      const t = v.currentTime || 0;
      // ⭐ Идём по словам, держим idx = последнее слово которое уже началось.
      // Между словами idx НЕ сбрасывается → overlay не мигает в gap'ах.
      // Только когда t > last.end + 2s — считаем что речь закончилась.
      let idx = -1;
      for (let i = 0; i < words.length; i++) {
        if (words[i].start <= t) idx = i;
        else break;
      }
      if (idx >= 0 && t > words[idx].end + 2.0) idx = -1;
      setActiveIdx((cur) => (cur !== idx ? idx : cur));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [words, enabled, videoRef]);

  // ⭐ deselect by Esc или click вне overlay
  React.useEffect(() => {
    if (!selected) return;
    const onKey = (e) => { if (e.key === "Escape") setSelected(false); };
    const onClick = (e) => {
      const target = e.target;
      // если клик ВНУТРИ overlay-wrap (или handle) — не deselect'им
      if (target.closest && target.closest("[data-sub-overlay]")) return;
      setSelected(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick, true);
    };
  }, [selected]);

  const scheduleSubsPatch = React.useCallback((patch) => {
    const c = clipRef.current;
    if (!c?._jobId || c.n == null) return;
    if (patchTimer.current) clearTimeout(patchTimer.current);
    patchTimer.current = setTimeout(() => {
      window.API.jobClipPatchSubOverrides(c._jobId, c.n, patch).catch(() => {});
      onLocalEditRef.current && onLocalEditRef.current();
    }, 220);
  }, []);

  // ⭐ pointer move/up handlers — глобальные, активны только во время drag
  React.useEffect(() => {
    const onMove = (e) => {
      const st = dragState.current;
      if (!st) return;
      e.preventDefault();
      const dy = (e.clientY - st.startY) / st.scale;  // CSS px → source px
      if (st.mode === "move") {
        // тяга вниз = меньше margin_v (overlay двигается вниз)
        const newMargin = Math.max(20, Math.min(st.videoH - 20, st.startMargin - dy));
        const patch = { margin_v: Math.round(newMargin) };
        setLocalOverrides((cur) => ({ ...cur, ...patch }));
        scheduleSubsPatch(patch);
      } else if (st.mode.startsWith("resize-")) {
        const dx = (e.clientX - st.startX) / st.scale;
        // ⭐ Угловые handle'ы (NW/NE/SW/SE) — пропорциональный resize size'а через
        // diagonal projection. Side handle'ы (N/S/E/W) — независимая ось:
        //  N/S → меняют только size (вертикально, без ширины)
        //  E/W → меняют max_chars_per_line (ширина wrap'а; больше chars = шире)
        const corner = (st.mode === "resize-NW" || st.mode === "resize-NE" ||
                        st.mode === "resize-SW" || st.mode === "resize-SE");
        if (corner) {
          let oDx = 0, oDy = 0;
          if (st.mode === "resize-SE") { oDx = 1; oDy = 1; }
          else if (st.mode === "resize-SW") { oDx = -1; oDy = 1; }
          else if (st.mode === "resize-NE") { oDx = 1; oDy = -1; }
          else if (st.mode === "resize-NW") { oDx = -1; oDy = -1; }
          const delta = (dx * oDx + dy * oDy) / Math.SQRT2;
          const newSize = Math.max(20, Math.min(140, st.startSize + delta * 0.6));
          const patch = { size: Math.round(newSize) };
          setLocalOverrides((cur) => ({ ...cur, ...patch }));
          scheduleSubsPatch(patch);
        } else if (st.mode === "resize-N" || st.mode === "resize-S") {
          // top/bottom — меняем только size; bottom drag вниз = больше, top drag вверх = больше
          const sign = (st.mode === "resize-S") ? 1 : -1;
          const delta = sign * dy;
          const newSize = Math.max(20, Math.min(140, st.startSize + delta * 0.6));
          const patch = { size: Math.round(newSize) };
          setLocalOverrides((cur) => ({ ...cur, ...patch }));
          scheduleSubsPatch(patch);
        } else if (st.mode === "resize-E" || st.mode === "resize-W") {
          // left/right — меняем max_chars_per_line; outward = больше chars
          const sign = (st.mode === "resize-E") ? 1 : -1;
          const delta = sign * dx;
          const newChars = Math.max(8, Math.min(60, st.startChars + delta * 0.05));
          const patch = { max_chars_per_line: Math.round(newChars) };
          setLocalOverrides((cur) => ({ ...cur, ...patch }));
          scheduleSubsPatch(patch);
        }
      }
    };
    const onUp = () => { dragState.current = null; };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [scheduleSubsPatch]);

  const startDrag = (e, mode) => {
    if (!selected) { setSelected(true); return; }
    e.stopPropagation();
    e.preventDefault();
    const video = videoRef.current;
    if (!video || !style) return;
    const rect = video.getBoundingClientRect();
    const videoH = style.canvas?.targetH || targetH;
    const scale = rect.height / videoH;  // CSS px per source px
    const baseSize = (style.preset && style.preset.size) || 56;
    const curSize = (localOverrides.size != null ? localOverrides.size : baseSize);
    const curMargin = (localOverrides.margin_v != null ? localOverrides.margin_v
                        : (style.preset && style.preset.margin_v) || 300);
    const baseChars = (style.preset && style.preset.max_chars_per_line) || 22;
    const curChars = (localOverrides.max_chars_per_line != null
                      ? localOverrides.max_chars_per_line : baseChars);
    dragState.current = {
      mode,
      startX: e.clientX, startY: e.clientY,
      startSize: curSize, startMargin: curMargin, startChars: curChars,
      scale, videoH,
    };
  };

  if (!enabled || !style || !words.length) return null;

  // ─── размер и позиция учитывают локальные overrides ────────────
  const baseSize = (style.preset && style.preset.size) || 56;
  const sizeOv = localOverrides.size != null ? localOverrides.size : baseSize;
  const marginOv = localOverrides.margin_v != null ? localOverrides.margin_v
                   : (style.preset && style.preset.margin_v) || 300;
  const baseChars = (style.preset && style.preset.max_chars_per_line) || 22;
  const maxCharsOv = localOverrides.max_chars_per_line != null
                     ? localOverrides.max_chars_per_line : baseChars;
  // text_scale формула (та же что в write_ass/sub_style) для перевода base size → px на текущем target_h
  const targetHActual = style.canvas?.targetH || targetH;
  const targetWActual = style.canvas?.targetW || Math.round(targetHActual * 9 / 16);
  const text_scale = targetHActual >= 1280 ? targetHActual / 1920
                    : targetHActual >= 720 ? (targetHActual / 1920) * 1.5
                    : (targetHActual / 1920) * 2.2;
  const effectiveFontSize = Math.max(14, Math.round(sizeOv * text_scale));
  const effectiveMarginPct = (marginOv / targetHActual) * 100;
  // ⭐ ширина wrapper'а от max_chars_per_line — emulates ASS auto-wrap
  // px ≈ chars × fontSize × 0.6 (средняя буква), переводим в % от ширины video.
  const wrapMaxPx = maxCharsOv * effectiveFontSize * 0.62;
  const wrapMaxPct = Math.min(96, Math.max(20, (wrapMaxPx / targetWActual) * 100));
  const liveStyle = { ...style, fontSize: effectiveFontSize };

  // Если selected, рендерим даже если activeIdx=-1 (между словами) — placeholder
  let chunkWords;
  if (activeIdx < 0) {
    if (!selected) return null;
    chunkWords = [{ text: words[0]?.text || "Это", kind: "plain" }];
  } else {
    const n = style.wordsPerChunk || 3;
    const adv = style.chunkAdvance || 1;
    let chunkStart = 0;
    if (adv === 1) {
      const half = Math.floor(n / 2);
      chunkStart = Math.max(0, activeIdx - half);
      const chunkEnd = Math.min(words.length, chunkStart + n);
      chunkStart = Math.max(0, chunkEnd - n);
    } else {
      chunkStart = Math.floor(activeIdx / adv) * adv;
    }
    const chunkSlice = words.slice(chunkStart, chunkStart + n);
    const useHighlight = !!(style.highlight && style.highlight.use);
    const chromaOn = (style.chromaCycle || []).length > 0;
    chunkWords = chunkSlice.map((w, j) => {
      const realIdx = chunkStart + j;
      let kind = "plain";
      if (adv === 1 && realIdx === activeIdx) {
        if (useHighlight) kind = "active";
        else if (chromaOn) kind = "chroma";
      } else if (style.useHighlight && adv > 1 && j === 0) {
        kind = "active";
      }
      return { text: w.text, kind };
    });
  }

  const wrapStyle = {
    position: "absolute",
    left: "50%",
    bottom: `${effectiveMarginPct}%`,
    transform: "translateX(-50%)",
    width: `${wrapMaxPct}%`,
    maxWidth: "96%",
    display: "flex",
    justifyContent: "center",
    zIndex: 5,
    // ⭐ НЕ ставим animation на wrap — она бы триггерилась на каждом chunk-change
    // и блок «пульсировал» по 4 раза в секунду. pop_in эмулируется per-word.
    cursor: selected ? "move" : "pointer",
    outline: selected ? "1.5px dashed rgba(255,255,255,0.85)" : "none",
    outlineOffset: "6px",
    padding: "2px 6px",
    userSelect: "none",
  };

  const handleStyle = {
    position: "absolute",
    width: 10, height: 10,
    background: "white",
    border: "1.5px solid rgba(10,13,10,0.85)",
    borderRadius: 2,
    pointerEvents: "auto",
  };

  return (
    <div
      data-sub-overlay
      style={wrapStyle}
      onClick={(e) => { e.stopPropagation(); setSelected(true); }}
      onPointerDown={(e) => startDrag(e, "move")}
    >
      <window.SubtitleChunk style={liveStyle} words={chunkWords}/>
      {selected && (
        <>
          {/* corners — proportional size */}
          <div data-sub-overlay style={{ ...handleStyle, top: -7, left: -7, cursor: "nwse-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-NW"); }}/>
          <div data-sub-overlay style={{ ...handleStyle, top: -7, right: -7, cursor: "nesw-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-NE"); }}/>
          <div data-sub-overlay style={{ ...handleStyle, bottom: -7, left: -7, cursor: "nesw-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-SW"); }}/>
          <div data-sub-overlay style={{ ...handleStyle, bottom: -7, right: -7, cursor: "nwse-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-SE"); }}/>
          {/* sides — top/bottom меняют size, left/right меняют ширину wrap'а */}
          <div data-sub-overlay style={{ ...handleStyle, top: -7, left: "50%", marginLeft: -5, cursor: "ns-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-N"); }}/>
          <div data-sub-overlay style={{ ...handleStyle, bottom: -7, left: "50%", marginLeft: -5, cursor: "ns-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-S"); }}/>
          <div data-sub-overlay style={{ ...handleStyle, left: -7, top: "50%", marginTop: -5, cursor: "ew-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-W"); }}/>
          <div data-sub-overlay style={{ ...handleStyle, right: -7, top: "50%", marginTop: -5, cursor: "ew-resize" }}
               onPointerDown={(e) => { e.stopPropagation(); startDrag(e, "resize-E"); }}/>
        </>
      )}
    </div>
  );
}

function ClipCard({ clip, t, onPublish, onMetrics, onChangeStyle, onClipRestyled, publishStatus = {} }) {
  const { Icon } = window.UI;
  const [tab, setTab] = React.useState("seo");
  const [openTrim, setOpenTrim] = React.useState(false);
  const [openReframe, setOpenReframe] = React.useState(false);
  const [openMusic, setOpenMusic] = React.useState(false);
  const [openBroll, setOpenBroll] = React.useState(false);
  const [openThumbs, setOpenThumbs] = React.useState(false);
  const [openCover, setOpenCover] = React.useState(false);
  const [openTranslate, setOpenTranslate] = React.useState(false);
  const [openSfx, setOpenSfx] = React.useState(false);
  const [copied, setCopied] = React.useState("");
  const videoRef = React.useRef(null);
  // ⭐ overlay по дефолту ВЫКЛ — иначе он показывается поверх burned субтитров
  // в финальном видео и пользователь видит два слоя текста. Авто-включается
  // когда юзер открывает edit-tab (для live-preview правок).
  const [overlayOn, setOverlayOn] = React.useState(false);
  const [subStyleVersion, setSubStyleVersion] = React.useState(0);
  const bumpSubStyle = () => setSubStyleVersion((v) => v + 1);
  // авто-вкл overlay при заходе в edit-tab
  React.useEffect(() => {
    if (tab === "edit") setOverlayOn(true);
  }, [tab]);
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
  // ⭐ В edit-tab показываем nosubs.mp4 (silent.mp4 + audio, без burned субтитров),
  // чтобы WYSIWYG-overlay не дублировал старые субтитры. В остальных табах — master.
  // _bust — query-busting после restyle для обновления кеша браузера.
  const masterUrl = clip._jobId && _masterFile
    ? `${window.API.clipUrl(clip._jobId, _masterFile)}${clip._bust ? `?v=${clip._bust}` : ""}`
    : null;
  const nosubsUrl = clip._jobId && clip.n != null
    ? `${window.API.jobClipNosubsUrl(clip._jobId, clip.n)}${clip._bust ? `?v=${clip._bust}` : ""}`
    : null;
  const videoUrl = (tab === "edit" && nosubsUrl) ? nosubsUrl : masterUrl;

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
          <>
            <video
              ref={videoRef}
              className="poster-video"
              src={videoUrl}
              playsInline
              controls
              preload="metadata"
              poster={clip._jobId
                ? window.API.thumbUrl(
                    clip._jobId,
                    // ⭐ Выбранная пользователем обложка (chosen_thumbnail) пути вида
                    // "thumbs/<slug>/2.jpg". thumbUrl сам префикснёт /clips/{jobId}/thumbs/
                    // поэтому из chosen_thumbnail убираем ведущий "thumbs/".
                    clip.chosen_thumbnail
                      ? clip.chosen_thumbnail.replace(/^thumbs\//, "")
                      : (clip._slug ? `${clip._slug}/0.jpg` : "")
                  ) + (clip._bust ? `?v=${clip._bust}` : "")
                : undefined}
              style={{
                position: "absolute", inset: 0, width: "100%", height: "100%",
                objectFit: "cover", background: "#000",
              }}
            />
            {/* WYSIWYG-overlay над видео — превью того, КАК будут выглядеть субтитры
                после re-render с текущим шаблоном. Совпадает с burn по pixel-level
                стилизации (один источник правды — sub_style.template_to_web_style). */}
            <SubtitleOverlay
              clip={clip}
              videoRef={videoRef}
              targetH={1056}
              enabled={overlayOn}
              styleVersion={subStyleVersion}
              onLocalEdit={bumpSubStyle}
            />
            {/* Toggle для overlay — по дефолту off, видны только burned субтитры */}
            <button
              title={overlayOn
                ? "Скрыть live-превью субтитров (видны burned в видео)"
                : "Показать live-превью субтитров (для редактирования)"}
              onClick={(e) => { e.stopPropagation(); setOverlayOn((v) => !v); }}
              style={{
                position: "absolute", top: 8, left: 8, zIndex: 6,
                height: 26, padding: "0 8px",
                background: overlayOn ? "var(--lime)" : "rgba(0,0,0,0.6)",
                color: overlayOn ? "var(--ink)" : "white",
                border: "none", borderRadius: 6,
                fontSize: 11, fontWeight: 700, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 4,
              }}
            >
              <span>Aa</span>
              <span style={{ opacity: 0.8 }}>{overlayOn ? "edit" : "off"}</span>
            </button>
          </>
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
        {/* убран poster-watermark Excella SVG в правом углу — мёртвый код, лого уже
            бернится в видео pipeline'ом, дублирующий overlay на превью не нужен */}
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
              {openThumbs && <div className="collapse-body"><ThumbnailsPanel clip={clip} onChosen={(rel) => onClipRestyled && onClipRestyled(clip.id, { chosen_thumbnail: rel })}/></div>}
            </div>

            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenCover(!openCover)}>
                <span>Обложка с хуком <span style={{ color: "var(--muted)", fontWeight: 400 }}>· большой текст поверх постера</span></span>
                <span className={"caret " + (openCover ? "open" : "")}>›</span>
              </button>
              {openCover && <div className="collapse-body"><CoverPanel clip={clip}/></div>}
            </div>

            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenTranslate(!openTranslate)}>
                <span>Перевести субтитры <span style={{ color: "var(--muted)", fontWeight: 400 }}>· EN/PT/ES/DE через Claude</span></span>
                <span className={"caret " + (openTranslate ? "open" : "")}>›</span>
              </button>
              {openTranslate && <div className="collapse-body"><TranslationPanel clip={clip}/></div>}
            </div>

            <div className="collapse" style={{ marginBottom: 10 }}>
              <button className="collapse-head" onClick={() => setOpenSfx(!openSfx)}>
                <span>Sound FX <span style={{ color: "var(--muted)", fontWeight: 400 }}>· whoosh/ding на акцентах</span></span>
                <span className={"caret " + (openSfx ? "open" : "")}>›</span>
              </button>
              {openSfx && <div className="collapse-body"><SfxPanel clip={clip}/></div>}
            </div>

            <SubtitleEditor
              clip={clip}
              onChangeStyle={onChangeStyle}
              onOverrideChange={bumpSubStyle}
              onClipRestyled={onClipRestyled}
            />
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

// ⭐ Section / Toggle — module-scope; объявление внутри компонента приводило бы
// к пересозданию типа компонента на каждый ре-рендер → React unmount'ит детей,
// и инпуты внутри теряли бы фокус после каждого нажатия клавиши.
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
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const badge = published
    ? <span className="badge-ok">{t.pubStatusPublished}</span>
    : isManual
      ? <span className="chip" style={{ fontSize: 11, padding: "3px 8px" }}>{t.pubManualBadge}</span>
      : connected
        ? <span className="badge-ok">{t.pubStatusConnected}</span>
        : <span className="badge-warn">{t.pubStatusNotConnected}</span>;
  const click = async () => {
    setError("");
    setBusy(true);
    try {
      const r = onPublish();
      if (r && typeof r.then === "function") await r;
    } catch (e) {
      setError(e?.message || String(e));
    } finally { setBusy(false); }
  };
  // эвристика: invalid_grant / 401 / 403 → конкретный совет переподключиться
  const hint2 = error && /invalid_grant|expired|revoked|401|403/i.test(error)
    ? "Токен YouTube/IG/VK истёк или отозван. Открой настройки бренда → Disconnect → снова Connect."
    : error && /uploadLimitExceeded|quotaExceeded/i.test(error)
      ? "Превышен дневной лимит загрузок YouTube для канала. Подожди 24 часа или верифицируй канал в YouTube Studio."
      : "";
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
      {error && (
        <div style={{
          marginTop: 10, padding: "8px 10px", borderRadius: 8,
          background: "rgba(224,74,63,0.12)", border: "1px solid rgba(224,74,63,0.4)",
          color: "var(--danger)", fontSize: 12, lineHeight: 1.4,
          wordBreak: "break-word",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Ошибка публикации:</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{error}</div>
          {hint2 && <div style={{ marginTop: 6, color: "var(--ink)" }}>{hint2}</div>}
        </div>
      )}
      <button
        className="btn btn-primary"
        style={{ width: "100%", justifyContent: "center", marginTop: 12 }}
        onClick={click}
        disabled={disabled || busy}
      >
        <Icon name="send" size={14}/> {busy ? "загружаю..." : (published ? t.pubReupload : t.pubPublishBtn)}
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
function ThumbnailsPanel({ clip, onChosen }) {
  const t = _i18n();
  const { Icon } = window.UI;
  const [thumbs, setThumbs] = React.useState(clip.thumbnails || []);
  const [chosen, setChosen] = React.useState(clip.chosen_thumbnail || "");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [saving, setSaving] = React.useState("");

  // sync если внешний clip обновился (например chosen_thumbnail с другого окна)
  React.useEffect(() => {
    setThumbs(clip.thumbnails || []);
    setChosen(clip.chosen_thumbnail || "");
  }, [clip.id, clip.chosen_thumbnail, clip.thumbnails]);

  const generate = async () => {
    if (!clip._jobId) return;
    setBusy(true); setError("");
    try {
      const r = await window.API.generateThumbnails(clip._jobId, clip._index + 1);
      setThumbs(r?.thumbnails || []);
      setChosen(r?.chosen_thumbnail || "");
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const choose = async (rel) => {
    if (!clip._jobId || rel === chosen) return;
    setSaving(rel); setError("");
    try {
      await window.API.jobClipSetChosenThumbnail(clip._jobId, clip._index + 1, rel);
      setChosen(rel);
      onChosen && onChosen(rel);  // notify parent → bumps poster URL
    } catch (e) { setError(e.message); }
    finally { setSaving(""); }
  };

  return (
    <div>
      {error && <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>{error}</div>}

      <div className="row-between" style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Извлекает 3 кандидата-кадра. Кликни по варианту, чтобы выбрать его как обложку — она пойдёт в публикации (YouTube/Instagram/VK).
        </div>
        <button className="btn btn-primary" onClick={generate} disabled={busy || !clip._jobId}>
          <Icon name="sparkles" size={13}/> {busy ? t.generating : (thumbs.length ? t.regenerate : t.generate)}
        </button>
      </div>

      {thumbs.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
          {thumbs.map((rel, i) => {
            const isChosen = rel === chosen;
            const isSaving = rel === saving;
            return (
              <button
                key={i}
                onClick={() => choose(rel)}
                disabled={isSaving}
                style={{
                  position: "relative",
                  padding: 0, textAlign: "left",
                  borderRadius: 10, overflow: "hidden", cursor: "pointer",
                  border: isChosen ? "3px solid var(--lime)" : "1px solid var(--line)",
                  background: "var(--bg-2)",
                  boxShadow: isChosen
                    ? "0 0 0 3px rgba(198,255,61,0.4), 0 8px 20px rgba(10,13,10,0.18)"
                    : "0 1px 0 rgba(255,255,255,0.6) inset",
                  opacity: isSaving ? 0.5 : 1,
                  transition: "all 0.12s ease",
                }}
              >
                <img
                  src={window.API.thumbUrl(clip._jobId, rel.replace(/^thumbs\//, ""))}
                  alt={`thumb ${i + 1}`}
                  style={{ display: "block", width: "100%", aspectRatio: "9/16", objectFit: "cover", background: "#000" }}
                />
                {isChosen && (
                  <span style={{
                    position: "absolute", top: 8, right: 8,
                    background: "var(--lime)", color: "var(--ink)",
                    borderRadius: 99, width: 26, height: 26,
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    fontWeight: 800, fontSize: 14,
                    boxShadow: "0 4px 10px rgba(10,13,10,0.3)",
                  }}>
                    <Icon name="check" size={14}/>
                  </span>
                )}
                <div style={{
                  padding: "6px 8px", fontSize: 11,
                  color: isChosen ? "var(--ink)" : "var(--muted)",
                  fontWeight: isChosen ? 700 : 400,
                  fontFamily: "var(--font-mono)", textAlign: "center",
                }}>
                  {isChosen ? "выбрано" : `#${i + 1}`}
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="hint">
          Нет извлечённых превью. Нажми «сгенерировать» — ffmpeg сделает 3 кадра из мастера.
        </div>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────
// CoverPanel — POST /clips/{i}/cover (наложение hook-текста на постер)
// ─────────────────────────────────────────────────────────────────
function CoverPanel({ clip }) {
  const { Icon } = window.UI;
  const initialHook = clip.cover_hook || clip.meta_title || clip.title || "";
  const [hookText, setHookText] = React.useState(initialHook);
  const [position, setPosition] = React.useState("top");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [bust, setBust] = React.useState(0);  // cache-buster для img src
  const [hasCover, setHasCover] = React.useState(!!clip.cover_image);

  React.useEffect(() => {
    setHookText(clip.cover_hook || clip.meta_title || clip.title || "");
    setHasCover(!!clip.cover_image);
  }, [clip.id, clip.cover_image]);

  const generate = async () => {
    if (!clip._jobId) return;
    setBusy(true); setError("");
    try {
      await window.API.jobClipGenerateCover(clip._jobId, clip._index + 1, {
        hook_text: hookText.trim(),
        text_position: position,
      });
      setHasCover(true);
      setBust(Date.now());
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const hasThumb = (clip.thumbnails || []).length > 0;

  return (
    <div>
      {error && (
        <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
        Текст-крючок поверх выбранного превью-кадра. Идёт как обложка (poster) при публикации в YouTube/IG/VK.
      </div>

      {!hasThumb && (
        <div className="hint" style={{ marginBottom: 12 }}>
          Сначала сгенерируй превью-кадры в секции выше.
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 220px", gap: 16, alignItems: "start" }}>
        <div>
          <label className="label">Текст-крючок</label>
          <textarea
            className="input"
            value={hookText}
            onChange={(e) => setHookText(e.target.value)}
            placeholder="Будет автоматически переведён в UPPERCASE"
            rows={2}
            style={{ width: "100%", resize: "vertical", fontFamily: "inherit" }}
          />
          <div style={{ marginTop: 12 }}>
            <label className="label">Позиция</label>
            <select className="select" value={position} onChange={(e) => setPosition(e.target.value)} style={{ width: "100%" }}>
              <option value="top">Вверху</option>
              <option value="center">По центру</option>
              <option value="bottom">Внизу</option>
            </select>
          </div>
          <button
            className="btn btn-primary"
            onClick={generate}
            disabled={busy || !clip._jobId || !hasThumb || !hookText.trim()}
            style={{ marginTop: 12 }}
          >
            <Icon name="sparkles" size={13}/> {busy ? "генерирую..." : (hasCover ? "перегенерировать" : "сгенерировать")}
          </button>
        </div>

        {hasCover ? (
          <div>
            <div className="label" style={{ marginBottom: 6 }}>Превью</div>
            <img
              src={window.API.jobClipCoverUrl(clip._jobId, clip._index + 1, bust)}
              alt="cover preview"
              style={{
                width: "100%", aspectRatio: "9/16", objectFit: "cover",
                borderRadius: 10, border: "1px solid var(--line)", background: "#000",
              }}
            />
          </div>
        ) : (
          <div style={{
            width: "100%", aspectRatio: "9/16",
            border: "1px dashed var(--line)", borderRadius: 10,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "var(--muted)", fontSize: 12, textAlign: "center", padding: 12,
          }}>
            Превью обложки появится здесь
          </div>
        )}
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────
// TranslationPanel — POST /clips/{i}/translate (RU→EN/PT/ES/...)
// ─────────────────────────────────────────────────────────────────
const TRANSLATE_LANGS = [
  { code: "en",    label: "English"  },
  { code: "pt-br", label: "Português (BR)" },
  { code: "es",    label: "Español"  },
  { code: "de",    label: "Deutsch"  },
];

function TranslationPanel({ clip }) {
  const { Icon } = window.UI;
  const [selected, setSelected] = React.useState(["en"]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [done, setDone] = React.useState(clip.translations || {});

  React.useEffect(() => {
    setDone(clip.translations || {});
  }, [clip.id, clip.translations]);

  const toggle = (code) => {
    setSelected((prev) => prev.includes(code)
      ? prev.filter((x) => x !== code)
      : [...prev, code]);
  };

  const run = async () => {
    if (!clip._jobId || selected.length === 0) return;
    setBusy(true); setError("");
    try {
      const r = await window.API.jobClipTranslate(clip._jobId, clip._index + 1, {
        target_langs: selected,
        source_lang: "ru",
      });
      setDone({ ...done, ...(r?.translations || {}) });
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <div>
      {error && (
        <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>
          {error}
        </div>
      )}
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
        Переводит субтитры через Claude и пере-рендерит мастер с новым ASS. Каждая версия — отдельный mp4 (1080p + варианты), готова к публикации в локальные каналы.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8, marginBottom: 12 }}>
        {TRANSLATE_LANGS.map((l) => {
          const isOn = selected.includes(l.code);
          const isDone = !!done[l.code];
          return (
            <button
              key={l.code}
              onClick={() => toggle(l.code)}
              disabled={busy}
              style={{
                padding: "10px 12px", borderRadius: 8,
                border: isOn ? "2px solid var(--lime)" : "1px solid var(--line)",
                background: isOn ? "rgba(198,255,61,0.12)" : "var(--bg-2)",
                cursor: "pointer", textAlign: "left",
                display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
              }}
            >
              <span style={{ fontWeight: isOn ? 700 : 400 }}>{l.label}</span>
              {isDone && <Icon name="check" size={13}/>}
            </button>
          );
        })}
      </div>

      <button
        className="btn btn-primary"
        onClick={run}
        disabled={busy || !clip._jobId || selected.length === 0}
      >
        <Icon name="sparkles" size={13}/> {busy ? `перевожу ${selected.length}...` : `перевести (${selected.length})`}
      </button>

      {Object.keys(done).length > 0 && (
        <div style={{ marginTop: 16, padding: 10, background: "var(--bg-2)", borderRadius: 8 }}>
          <div className="label" style={{ marginBottom: 6 }}>Готовые переводы</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {Object.entries(done).map(([code, info]) => {
              const lang = TRANSLATE_LANGS.find((l) => l.code === code);
              const url = info.files?.["1080p"]
                ? window.API.clipUrl(clip._jobId, info.files["1080p"])
                : null;
              return (
                <a key={code}
                  href={url || "#"} target="_blank" rel="noopener"
                  style={{ padding: "4px 10px", border: "1px solid var(--line)", borderRadius: 99, fontSize: 12, color: "var(--ink)", textDecoration: "none" }}
                >
                  {lang?.label || code} ↗
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────
// SfxPanel — POST /clips/{i}/add-sfx (whoosh/ding на акцентах)
// ─────────────────────────────────────────────────────────────────
function SfxPanel({ clip }) {
  const { Icon } = window.UI;
  const [style, setStyle] = React.useState(clip.sfx?.style || "subtle");
  const [enableCuts, setEnableCuts] = React.useState(true);
  const [enableSpeech, setEnableSpeech] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState(clip.sfx || null);

  React.useEffect(() => {
    setResult(clip.sfx || null);
    setStyle(clip.sfx?.style || "subtle");
  }, [clip.id, clip.sfx]);

  const run = async () => {
    if (!clip._jobId) return;
    setBusy(true); setError("");
    try {
      const r = await window.API.jobClipAddSfx(clip._jobId, clip._index + 1, {
        style,
        enable_cuts: enableCuts,
        enable_speech_onset: enableSpeech,
      });
      setResult({ style, n_stings: r?.n_stings || 0, files: r?.files || {} });
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const url = result?.files?.["1080p"]
    ? window.API.clipUrl(clip._jobId, result.files["1080p"])
    : null;

  return (
    <div>
      {error && (
        <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 12 }}>
          {error}
        </div>
      )}
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
        Накладывает короткие звуки (whoosh / ding) на cut'ы и моменты начала речи. Тайминги — из уже сделанного analysis.pkl, без новой детекции.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        <button
          onClick={() => setStyle("subtle")}
          style={{
            padding: "10px 12px", borderRadius: 8,
            border: style === "subtle" ? "2px solid var(--lime)" : "1px solid var(--line)",
            background: style === "subtle" ? "rgba(198,255,61,0.12)" : "var(--bg-2)",
            cursor: "pointer", fontWeight: style === "subtle" ? 700 : 400,
          }}
        >
          Subtle <span style={{ color: "var(--muted)", fontWeight: 400 }}>· swoosh+pop тихо</span>
        </button>
        <button
          onClick={() => setStyle("energetic")}
          style={{
            padding: "10px 12px", borderRadius: 8,
            border: style === "energetic" ? "2px solid var(--lime)" : "1px solid var(--line)",
            background: style === "energetic" ? "rgba(198,255,61,0.12)" : "var(--bg-2)",
            cursor: "pointer", fontWeight: style === "energetic" ? 700 : 400,
          }}
        >
          Energetic <span style={{ color: "var(--muted)", fontWeight: 400 }}>· whoosh+ding громко</span>
        </button>
      </div>

      <div style={{ display: "flex", gap: 16, marginBottom: 12, fontSize: 13 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={enableCuts} onChange={(e) => setEnableCuts(e.target.checked)}/>
          На cut'ы (swoosh)
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={enableSpeech} onChange={(e) => setEnableSpeech(e.target.checked)}/>
          На начало речи (pop/ding)
        </label>
      </div>

      <button
        className="btn btn-primary"
        onClick={run}
        disabled={busy || !clip._jobId || (!enableCuts && !enableSpeech)}
      >
        <Icon name="sparkles" size={13}/> {busy ? "накладываю..." : (result ? "переналожить" : "наложить SFX")}
      </button>

      {result && (
        <div style={{ marginTop: 16, padding: 10, background: "var(--bg-2)", borderRadius: 8, fontSize: 13 }}>
          <div style={{ marginBottom: 6 }}>
            Готово: {result.n_stings} стингов в стиле <strong>{result.style}</strong>
          </div>
          {url && (
            <a href={url} target="_blank" rel="noopener" style={{ fontSize: 12 }}>
              открыть master_sfx ↗
            </a>
          )}
        </div>
      )}
    </div>
  );
}


// ──────────── Vizard-style subtitle editor ────────────
// Toolbar для редактирования стиля субтитров текущего клипа. Все изменения
// идут через PATCH /sub-overrides (мгновенно подхватываются overlay'ем),
// финальный re-render — кнопкой Apply (POST /restyle).
function SubtitleEditor({ clip, onChangeStyle, onOverrideChange, onClipRestyled }) {
  const { Icon } = window.UI;
  const SUBTITLE_STYLES = window.MOCK.SUBTITLE_STYLES || [];
  const [overrides, setOverrides] = React.useState(clip.sub_overrides || {});
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  // sync если смена клипа или внешнее обновление
  React.useEffect(() => {
    setOverrides(clip.sub_overrides || {});
  }, [clip.id, clip.sub_overrides]);

  const debouncedPatch = React.useRef(null);
  const setField = (k, v) => {
    setOverrides((cur) => ({ ...cur, [k]: v }));
    onOverrideChange && onOverrideChange();
    if (!clip._jobId || clip.n == null) return;
    if (debouncedPatch.current) clearTimeout(debouncedPatch.current);
    debouncedPatch.current = setTimeout(() => {
      window.API.jobClipPatchSubOverrides(clip._jobId, clip.n, { [k]: v })
        .then(() => { onOverrideChange && onOverrideChange(); })
        .catch((e) => setMsg(`Ошибка: ${e.message}`));
    }, 220);
  };

  const resetOverrides = async () => {
    if (!clip._jobId || clip.n == null) return;
    try {
      await window.API.jobClipResetSubOverrides(clip._jobId, clip.n);
      setOverrides({});
      onOverrideChange && onOverrideChange();
      setMsg("Сброшено");
      setTimeout(() => setMsg(""), 1500);
    } catch (e) { setMsg(`Ошибка: ${e.message}`); }
  };

  const apply = async () => {
    if (!clip._jobId || clip.n == null) return;
    setBusy(true); setMsg("");
    try {
      const resp = await window.API.jobClipRestyle(clip._jobId, clip.n, {
        template: clip.activeStyle || "block",
        overrides,
      });
      setMsg("Готово — новый файл");
      onOverrideChange && onOverrideChange();
      if (resp && resp.clip && onClipRestyled) {
        onClipRestyled(clip.id, resp.clip);
      }
    } catch (e) {
      setMsg(`Ошибка: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  // ⭐ Inline-функции вместо вложенных компонентов — иначе React unmount'ит инпут на каждый
  // setOverrides и слайдер «прыгает» на одно деление и стопорится.
  const sliderOf = (label, k, min, max, defValue, step = 1) => (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginBottom: 6 }}>
      <span style={{ minWidth: 80, color: "var(--muted)" }}>{label}</span>
      <input type="range" min={min} max={max} step={step}
             value={overrides[k] ?? defValue}
             onChange={(e) => setField(k, Number(e.target.value))}
             style={{ flex: 1 }}/>
      <span style={{ minWidth: 36, fontVariantNumeric: "tabular-nums", textAlign: "right" }}>
        {overrides[k] ?? defValue}
      </span>
    </div>
  );
  const colorOf = (label, k, defValue) => (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginBottom: 6 }}>
      <span style={{ minWidth: 80, color: "var(--muted)" }}>{label}</span>
      <input type="color"
             value={overrides[k] ?? defValue}
             onChange={(e) => setField(k, e.target.value)}
             style={{ width: 36, height: 24, border: "none", padding: 0, background: "transparent" }}/>
      <code style={{ fontSize: 11, color: "var(--muted)" }}>{overrides[k] ?? defValue}</code>
    </label>
  );
  const toggleOf = (label, k, defValue) => (
    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginBottom: 6, cursor: "pointer" }}>
      <input type="checkbox"
             checked={overrides[k] ?? defValue}
             onChange={(e) => setField(k, e.target.checked)}/>
      <span>{label}</span>
    </label>
  );

  return (
    <div>
      <label className="label">Шаблон субтитров</label>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 8, marginBottom: 14 }}>
        {SUBTITLE_STYLES.map((s) => {
          const isActive = clip.activeStyle === s.id;
          return (
            <button
              key={s.id}
              onClick={() => {
                onChangeStyle(clip.id, s.id);
                // ⭐ сразу же сохраняем в backend, чтобы overlay (который фетчит /sub-style)
                // подхватил новый шаблон без необходимости Apply
                if (clip._jobId && clip.n != null) {
                  window.API.jobClipPatchSubTemplate(clip._jobId, clip.n, s.id)
                    .then(() => onOverrideChange && onOverrideChange())
                    .catch(() => {});
                } else {
                  onOverrideChange && onOverrideChange();
                }
              }}
              style={{
                cursor: "pointer",
                border: isActive ? "2px solid var(--ink)" : "1px solid var(--line)",
                borderRadius: 12, padding: 10,
                background: isActive ? "var(--bg-3)" : "var(--bg-2)",
                boxShadow: isActive
                  ? "0 0 0 3px var(--lime), 0 6px 16px rgba(10,13,10,0.10)"
                  : "0 1px 0 rgba(255,255,255,0.6) inset",
                display: "flex", flexDirection: "column", gap: 8, textAlign: "left",
              }}
            >
              <div style={{
                height: 44, borderRadius: 8,
                background: "linear-gradient(180deg, #2b2f36, #0e1014)",
                position: "relative", overflow: "hidden",
                display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                <window.SubtitlePreviewFromKey id={s.id}/>
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

      <div className="collapse" style={{ marginBottom: 10 }}>
        <button className="collapse-head"><span>Размер и позиция</span></button>
        <div className="collapse-body">
          {sliderOf("Шрифт", "size", 20, 120, 56)}
          {sliderOf("Поле снизу", "margin_v", 40, 500, 300)}
          {sliderOf("Толщина обводки", "outline", 0, 12, 4)}
          {sliderOf("Тень", "shadow", 0, 8, 2)}
          {sliderOf("Letter-spacing", "letter_spacing", 0, 6, 0)}
        </div>
      </div>

      <div className="collapse" style={{ marginBottom: 10 }}>
        <button className="collapse-head"><span>Цвет</span></button>
        <div className="collapse-body">
          {colorOf("Текст", "color", "#FFFFFF")}
          {colorOf("Подсветка", "highlight", "#FFE600")}
          {colorOf("Акцент", "accent_color", "#FFE600")}
          {colorOf("Обводка", "outline_color", "#000000")}
        </div>
      </div>

      <div className="collapse" style={{ marginBottom: 10 }}>
        <button className="collapse-head"><span>Стиль</span></button>
        <div className="collapse-body">
          {toggleOf("Жирный", "bold", true)}
          {toggleOf("UPPERCASE", "uppercase", false)}
          {toggleOf("Pop-in анимация", "pop_in", false)}
          {toggleOf("Капитализация", "auto_capitalize", true)}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
        <button className="btn btn-primary" onClick={apply} disabled={busy || !clip._jobId}>
          {busy ? "Рендер..." : "Применить (re-render)"}
        </button>
        <button className="btn btn-ghost" onClick={resetOverrides} disabled={!Object.keys(overrides).length}>
          Сбросить правки
        </button>
        {msg && <span style={{ fontSize: 12, color: "var(--muted)" }}>{msg}</span>}
      </div>
      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 8 }}>
        Изменения видны в WYSIWYG-overlay над видео сразу. «Применить» делает burn в финальный файл (~30с).
      </div>
    </div>
  );
}

window.PROGRESSCLIPS = { ProgressBlock, RecentJobs, ClipCard };
