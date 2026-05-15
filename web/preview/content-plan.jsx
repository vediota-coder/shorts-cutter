// === Content Plan screen ===
const { useState, useEffect, useMemo } = React;

const styles = {
  // Поверхности (3 уровня глубины)
  page: { background: "var(--bg)" },               // фон страницы
  card: { background: "var(--bg-2)", border: "1px solid var(--line)" }, // карточки, модалки
  inset: { background: "var(--bg-3)", border: "1px solid var(--line)" }, // input, text-box внутри карточек

  // Текст
  ink: { color: "var(--ink)" },
  muted: { color: "var(--muted)" },

  // Шрифты
  display: { fontFamily: "Unbounded, sans-serif" },
  body: { fontFamily: "Inter, system-ui, sans-serif" },
};

const tone = {
  // активный chip / акцентная кнопка
  accent: { background: "var(--lime)", color: "#11140F", border: "1px solid var(--lime)" },
  // неактивный chip-button
  chip: { background: "var(--bg-3)", color: "var(--ink)", border: "1px solid var(--line)" },
  // viral
  viral: { background: "#FFC83D", color: "#11140F", border: "1px solid #FFC83D" },
};

function fmtViews(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return Math.round(n / 1e3) + "K";
  return String(n);
}

function Stars({ score }) {
  return (
    <span style={{ display: "inline-flex", gap: 2 }}>
      {[1, 2, 3, 4, 5].map(i => (
        <span key={i} style={{ color: i <= score ? "#FFC83D" : "var(--line)", fontSize: 14, textShadow: i <= score ? "0 0 4px rgba(255,200,61,.4)" : "none" }}>★</span>
      ))}
    </span>
  );
}

function Chip({ active, viral, onClick, children }) {
  const s = active ? (viral ? tone.viral : tone.accent) : tone.chip;
  return (
    <button onClick={onClick} style={{
      ...s, ...styles.body,
      padding: "6px 12px", borderRadius: 999, fontSize: 12, cursor: "pointer",
      fontWeight: active ? 700 : 500
    }}>{children}</button>
  );
}

function RewriteModal({ video, rewrites, categories, onClose, onRecord }) {
  const versions = rewrites[video.id] || [];
  const tabs = [];
  if (video.transcript) tabs.push({ key: "orig", label: "📝 Оригинал" });
  versions.forEach((r, i) => tabs.push({ key: "rw" + i, label: r.product, score: r.score, idx: i }));
  const [active, setActive] = useState(tabs[0]?.key || "");

  function copy(text, btn) {
    navigator.clipboard.writeText(text);
    const old = btn.textContent;
    btn.textContent = "✓ скопировано";
    setTimeout(() => { btn.textContent = old; }, 1500);
  }

  const activeTab = tabs.find(t => t.key === active);

  return (
    <div onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100, padding: 20, backdropFilter: "blur(6px)" }}>
      <div style={{
        ...styles.card, ...styles.ink,
        width: "100%", maxWidth: 900, maxHeight: "90vh",
        display: "flex", flexDirection: "column", overflow: "hidden",
        borderRadius: 16, boxShadow: "0 40px 100px rgba(0,0,0,.4)"
      }}>
        {/* Заголовок */}
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line)", display: "flex", gap: 14, alignItems: "flex-start" }}>
          <div style={{ flex: 1, minWidth: 0, paddingRight: 8 }}>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, lineHeight: 1.4, ...styles.display, ...styles.ink }}>{video.title}</h2>
            <div style={{ ...styles.muted, fontSize: 12, marginTop: 6, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <span>👁 {fmtViews(video.view_count)}</span>
              {video.is_viral && <span style={{ color: "#E0A800", fontWeight: 600 }}>🔥 залетел</span>}
              <span>{video.categories.map(c => categories[c] || c).join(" · ")}</span>
              <a href={video.url} target="_blank" rel="noopener" style={{ color: "var(--lime-deep)", textDecoration: "none", fontWeight: 600 }}>▶ открыть на YouTube</a>
            </div>
          </div>
          <button onClick={onClose} style={{
            ...tone.chip, width: 32, height: 32, borderRadius: 8, cursor: "pointer", fontSize: 18, flexShrink: 0, lineHeight: 1
          }}>×</button>
        </div>

        {/* Табы */}
        <div style={{ display: "flex", gap: 6, padding: "10px 20px", borderBottom: "1px solid var(--line)", overflowX: "auto", background: "var(--bg)" }}>
          {tabs.map(t => {
            const isActive = active === t.key;
            return (
              <button key={t.key} onClick={() => setActive(t.key)}
                style={{
                  ...(isActive ? tone.accent : tone.chip), ...styles.body,
                  padding: "7px 12px", borderRadius: 8, fontSize: 12, fontWeight: isActive ? 700 : 500,
                  cursor: "pointer", whiteSpace: "nowrap", display: "inline-flex", gap: 6, alignItems: "center"
                }}>
                {t.label} {t.score && <span style={{ fontSize: 10, background: isActive ? "rgba(0,0,0,.18)" : "var(--bg)", padding: "1px 5px", borderRadius: 4 }}>{t.score}/5</span>}
              </button>
            );
          })}
        </div>

        {/* Контент */}
        <div style={{ padding: 20, overflowY: "auto", flex: 1, background: "var(--bg-2)" }}>
          {activeTab && activeTab.key === "orig" && (
            <div>
              <h3 style={sectionLabel}>Оригинал транскрипции</h3>
              <div style={textBox(false)}>
                {video.transcript}
                <button onClick={(e) => copy(video.transcript, e.target)} style={copyBtn}>копировать</button>
              </div>
            </div>
          )}
          {activeTab && activeTab.idx !== undefined && (() => {
            const r = versions[activeTab.idx];
            return (
              <div>
                <h3 style={sectionLabel}>Версия под: {r.product}</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                  <Stars score={r.score} />
                  <span style={{ ...styles.muted, fontSize: 12 }}>релевантность {r.score}/5</span>
                  <button
                    onClick={() => onRecord(video.id, activeTab.idx)}
                    style={{ ...tone.accent, ...styles.body, marginLeft: "auto", padding: "7px 16px", borderRadius: 8, fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
                    ▶ Записать
                  </button>
                </div>
                <div style={textBox(true)}>
                  {r.text}
                  <button onClick={(e) => copy(r.text, e.target)} style={copyBtn}>копировать</button>
                </div>
              </div>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

const sectionLabel = {
  margin: "0 0 10px", fontSize: 11, color: "var(--muted)",
  textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 600,
  fontFamily: "Inter, sans-serif"
};

function textBox(isRewrite) {
  return {
    background: isRewrite ? "var(--lime-soft)" : "var(--bg-3)",
    border: "1px solid " + (isRewrite ? "var(--lime)" : "var(--line)"),
    borderRadius: 10, padding: 14, whiteSpace: "pre-wrap",
    fontSize: 13, lineHeight: 1.65, position: "relative",
    color: isRewrite ? "#11140F" : "var(--ink)",
    fontFamily: "Inter, sans-serif"
  };
}

const copyBtn = {
  position: "absolute", top: 10, right: 10,
  background: "var(--bg-2)", border: "1px solid var(--line)", color: "var(--ink)",
  padding: "4px 10px", borderRadius: 6, fontSize: 11, cursor: "pointer", fontWeight: 500,
  fontFamily: "Inter, sans-serif"
};

function Hint({ children }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onClick={(e) => { e.preventDefault(); setOpen(o => !o); }}
      style={{ position: "relative", display: "inline-flex", alignItems: "center", verticalAlign: "middle", cursor: "help" }}
    >
      <svg width="11" height="11" viewBox="0 0 16 16" fill="none" style={{
        opacity: open ? 1 : .55,
        color: open ? "var(--lime-deep)" : "var(--muted)",
        transition: "opacity .15s, color .15s",
      }}>
        <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.4" fill="none"/>
        <path d="M8 4.5v.01M8 7.2v4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      </svg>
      {open && (
        <span style={{
          position: "absolute", top: "calc(100% + 6px)", right: 0,
          background: "var(--ink)", color: "var(--bg-2)",
          padding: "10px 14px", borderRadius: 8, fontSize: 11, lineHeight: 1.55,
          width: 280, zIndex: 50, pointerEvents: "none",
          textTransform: "none", letterSpacing: 0, fontWeight: 400,
          fontFamily: "Inter, sans-serif",
          boxShadow: "0 12px 32px rgba(0,0,0,.25)"
        }}>{children}</span>
      )}
    </span>
  );
}

// Label-обёртка: текст слева, иконка-подсказка в правом верхнем углу
function Label({ children, hint, style }) {
  return (
    <div style={{ ...tpLabelL, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, ...style }}>
      <span>{children}</span>
      {hint && <Hint>{hint}</Hint>}
    </div>
  );
}

function ImportForm({ onImported }) {
  const [url, setUrl] = useState("");
  const [topN, setTopN] = useState(50);
  const [fetchTr, setFetchTr] = useState(true);
  const [whisperFb, setWhisperFb] = useState(false);
  const [genRw, setGenRw] = useState(false);
  const [topicsText, setTopicsText] = useState(
    "Холодные B2B продажи\nПродажи и продвижение на Авито\nEmail outreach\nКонтент-маркетинг и YouTube\nAI/автоматизация для увеличения LTV\nПродажи на большой чек"
  );
  const [productsText, setProductsText] = useState(
    "AI-виджет для Авито\nEmail outreach в B2B\nB2B продажи / большой чек\nAI-аналитика / автоматизация\nКонтент / спикер"
  );
  const [persona, setPersona] = useState(
    "Тон: без пафоса и коуч-штампов. Только конкретные истории из своей практики. Короткие фразы под живую речь, по одному выдоху на строку. Формула шортса: ХУК (≤12 слов) → ЗАЦЕП → ПОВОРОТ → ЗАМОК. Продукт называю 'мультиагент' (не бот), своё преимущество — 'опыт' (не стиль)."
  );
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    fetch("/api/content-plan/import/providers").then(r => r.json()).then(d => {
      setProviders(d.providers || []);
      const def = (d.providers || []).find(p => p.configured);
      if (def) {
        setProvider(def.name);
        setModel((def.models || [])[0] || "");
      }
    });
  }, []);

  useEffect(() => {
    if (!polling) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/content-plan/import/status");
        const s = await r.json();
        setStatus(s);
        if (s.status === "done" || s.status === "error") {
          setPolling(false);
          if (s.status === "done") onImported?.();
          return;
        }
      } catch (e) {}
      if (!stop) setTimeout(tick, 1000);
    };
    tick();
    return () => { stop = true; };
  }, [polling]);

  const onStart = async () => {
    const products = productsText.split("\n").map(s => s.trim()).filter(Boolean);
    const topics = topicsText.split("\n").map(s => s.trim()).filter(Boolean);
    const r = await fetch("/api/content-plan/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url, top_n: topN,
        fetch_transcripts: fetchTr, whisper_fallback: whisperFb,
        generate_rewrites: genRw,
        products, topics, persona, provider, model
      })
    });
    const j = await r.json();
    if (!j.ok) {
      alert(j.error || "Ошибка запуска");
      return;
    }
    setPolling(true);
    setStatus({ status: "running", step: "Старт", progress: 0, log: [] });
  };

  const running = status?.status === "running";
  const curProviderModels = providers.find(p => p.name === provider)?.models || [];

  return (
    <div style={{ ...styles.card, padding: "20px 24px", marginBottom: 20, borderRadius: 16, boxShadow: "0 4px 20px rgba(17,20,15,.04)" }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, ...styles.display, ...styles.ink }}>Импорт канала</h2>
      <p style={{ ...styles.muted, fontSize: 12, marginTop: 4, marginBottom: 16 }}>
        Вставь ссылку на YouTube-канал → распарсим shorts, скачаем транскрипции, сгенерируем рерайты под твои продукты.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <Label hint="Любая страница YouTube-канала. Если ссылка без /shorts — добавим автоматически. Поддерживается формат @имя, /channel/UC…, /c/имя.">URL канала</Label>
          <input value={url} onChange={e => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/@grebenukm"
            style={{ ...styles.inset, ...styles.ink, padding: "9px 14px", borderRadius: 8, fontSize: 13, width: "100%", ...styles.body, outline: "none" }} />

          <Label hint="По умолчанию 50. Сортируется по просмотрам. Влияет только на транскрипции и рерайты — все метаданные парсятся полностью.">Сколько топ-шортсов обрабатывать</Label>
          <input type="number" value={topN} onChange={e => setTopN(parseInt(e.target.value) || 50)} min={10} max={1000}
            style={{ ...styles.inset, ...styles.ink, padding: "9px 14px", borderRadius: 8, fontSize: 13, width: 120, ...styles.body, outline: "none" }} />

          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", color: "var(--ink)" }}>
              <input type="checkbox" checked={fetchTr} onChange={e => setFetchTr(e.target.checked)} />
              Скачать субтитры YouTube
              <Hint>youtube-transcript-api — берёт готовые субтитры из YouTube без скачивания видео. Мгновенно, без лимитов. Покрытие ~20-40% (только шортсы с включёнными ru/en captions).</Hint>
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", color: "var(--ink)", opacity: fetchTr ? 1 : .5 }}>
              <input type="checkbox" checked={whisperFb} onChange={e => setWhisperFb(e.target.checked)} disabled={!fetchTr} />
              Whisper-fallback (stream)
              <Hint>Для шортсов без субтитров: качаем только аудио (~500KB), транскрибируем через Whisper, удаляем файл. Память не растёт. На M-чипе MLX даёт ~30× realtime — 200 шортсов = ~3-5 мин. Покрытие после fallback: 95-100%.</Hint>
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", color: "var(--ink)" }}>
              <input type="checkbox" checked={genRw} onChange={e => setGenRw(e.target.checked)} />
              Сгенерировать рерайты через LLM
              <Hint>Для каждого шортса с транскрипцией LLM сгенерирует по одному рерайту под каждый продукт из списка справа. Платно по токенам у API-провайдеров, бесплатно у CLI с подпиской.</Hint>
            </label>
          </div>

          {genRw && (
            <>
              <Label hint="Сконфигурированные провайдеры доступны для выбора. Чтобы добавить — настрой ключ в .env или подключи подписку (claude-code login и т.п.).">LLM провайдер</Label>
              <select value={provider} onChange={e => { setProvider(e.target.value); setModel(""); }}
                style={{ ...styles.inset, ...styles.ink, padding: "8px 12px", borderRadius: 8, fontSize: 12, width: "100%", ...styles.body }}>
                {providers.map(p => (
                  <option key={p.name} value={p.name} disabled={!p.configured}>
                    {p.label} {p.configured ? "" : "(не настроен)"}
                  </option>
                ))}
              </select>

              {curProviderModels.length > 0 && (
                <>
                  <Label hint="Чем выше модель тем качественнее рерайт, но дороже. Для рерайтов 50 шортсов средняя модель обычно достаточна.">Модель</Label>
                  <select value={model} onChange={e => setModel(e.target.value)}
                    style={{ ...styles.inset, ...styles.ink, padding: "8px 12px", borderRadius: 8, fontSize: 12, width: "100%", ...styles.body }}>
                    {curProviderModels.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </>
              )}
            </>
          )}
        </div>

        <div>
          <Label hint="Как ты говоришь и пишешь — для LLM. Описываешь голос, любимые приёмы, чего избегать. Это шапка системного промпта для рерайта.">Персона / тон</Label>
          <textarea value={persona} onChange={e => setPersona(e.target.value)} rows={5}
            style={{ ...styles.inset, ...styles.ink, padding: "9px 14px", borderRadius: 8, fontSize: 12, width: "100%", ...styles.body, outline: "none", resize: "vertical", lineHeight: 1.5 }} />

          <Label hint="Темы, которые тебе интересны в этом канале. LLM использует список чтобы при рерайте ловить наиболее релевантные оригиналы и подбирать к ним метафоры.">Темы</Label>
          <textarea value={topicsText} onChange={e => setTopicsText(e.target.value)} rows={4}
            placeholder="по одной теме в строку"
            style={{ ...styles.inset, ...styles.ink, padding: "9px 14px", borderRadius: 8, fontSize: 12, width: "100%", ...styles.body, outline: "none", resize: "vertical", lineHeight: 1.5 }} />

          <Label hint="Конкретные продукты под которые делаем рерайт. На каждый оригинал LLM выдаст по одной версии под каждый продукт + оценку релевантности 1-5. По одной строке на продукт.">Продукты</Label>
          <textarea value={productsText} onChange={e => setProductsText(e.target.value)} rows={4}
            placeholder="по одному продукту в строку"
            style={{ ...styles.inset, ...styles.ink, padding: "9px 14px", borderRadius: 8, fontSize: 12, width: "100%", ...styles.body, outline: "none", resize: "vertical", lineHeight: 1.5 }} />
        </div>
      </div>

      <button onClick={onStart} disabled={!url || running}
        style={{
          ...tone.accent, ...styles.body,
          marginTop: 18, padding: "11px 22px", borderRadius: 10, fontSize: 14, fontWeight: 700,
          cursor: (url && !running) ? "pointer" : "not-allowed",
          opacity: (url && !running) ? 1 : .5
        }}>
        {running ? "Импорт идёт…" : "▶ Запустить анализ"}
      </button>

      {status && (
        <div style={{ marginTop: 20, padding: 16, ...styles.inset, borderRadius: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>{status.step || "…"}</div>
            <div style={{ fontSize: 12, color: status.status === "error" ? "#e63946" : status.status === "done" ? "var(--lime-deep)" : "var(--muted)" }}>
              {status.status === "done" ? "✓ Готово" : status.status === "error" ? "✗ Ошибка" : `${status.progress || 0}%`}
            </div>
          </div>
          <div style={{ height: 6, background: "var(--bg)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{
              width: `${status.progress || 0}%`, height: "100%",
              background: status.status === "error" ? "#e63946" : "var(--lime)",
              transition: "width .3s"
            }}></div>
          </div>
          {status.result && (
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>
              Видео: <b style={styles.ink}>{status.result.total_videos}</b> ·
              Залетевших: <b style={styles.ink}>{status.result.viral_count}</b> ·
              Транскрипций: <b style={styles.ink}>{status.result.transcripts}</b> ·
              Рерайтов: <b style={styles.ink}>{status.result.rewrites}</b>
            </div>
          )}
          {(status.log || []).length > 0 && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: "var(--muted)", fontWeight: 600 }}>Лог</summary>
              <pre style={{ fontSize: 10, color: "var(--muted)", maxHeight: 200, overflow: "auto", fontFamily: "ui-monospace, monospace", margin: "6px 0 0", whiteSpace: "pre-wrap" }}>
                {(status.log || []).slice(-30).join("\n")}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

const tpLabelL = { display: "block", fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", fontWeight: 600, marginTop: 12, marginBottom: 6, fontFamily: "Inter, sans-serif" };

function ContentPlanScreen({ onOpenPrompter }) {
  const [tab, setTab] = useState("import"); // import | catalog (по умолчанию открыт импорт)
  const [data, setData] = useState(null);
  const [rewrites, setRewrites] = useState({});
  const [search, setSearch] = useState("");
  const [activeCat, setActiveCat] = useState(null);
  const [viralOnly, setViralOnly] = useState(false);
  const [hasRewriteOnly, setHasRewriteOnly] = useState(false);
  const [sort, setSort] = useState("views");
  const [selected, setSelected] = useState(null);
  const [transcripts, setTranscripts] = useState({});
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    fetch("/api/content-plan/videos").then(r => r.json()).then(setData);
    fetch("/api/content-plan/rewrites").then(r => r.json()).then(setRewrites);
  }, [reloadKey]);

  useEffect(() => {
    if (selected && !transcripts[selected.id]) {
      fetch(`/api/content-plan/transcript/${selected.id}`)
        .then(r => r.json())
        .then(d => setTranscripts(t => ({ ...t, [selected.id]: d.text || "" })));
    }
  }, [selected]);

  const filtered = useMemo(() => {
    if (!data) return [];
    let arr = data.videos.slice();
    if (search) {
      const q = search.toLowerCase();
      arr = arr.filter(v =>
        v.title.toLowerCase().includes(q) ||
        (rewrites[v.id] || []).some(r => r.text.toLowerCase().includes(q) || r.product.toLowerCase().includes(q))
      );
    }
    if (activeCat) arr = arr.filter(v => v.categories.includes(activeCat));
    if (viralOnly) arr = arr.filter(v => v.is_viral);
    if (hasRewriteOnly) arr = arr.filter(v => (rewrites[v.id] || []).length > 0);
    if (sort === "views") arr.sort((a, b) => b.view_count - a.view_count);
    else if (sort === "views-asc") arr.sort((a, b) => a.view_count - b.view_count);
    else if (sort === "title") arr.sort((a, b) => a.title.localeCompare(b.title, "ru"));
    return arr;
  }, [data, rewrites, search, activeCat, viralOnly, hasRewriteOnly, sort]);

  const catStats = useMemo(() => {
    if (!data) return [];
    const counts = {};
    data.videos.forEach(v => v.categories.forEach(c => counts[c] = (counts[c] || 0) + 1));
    return Object.entries(counts)
      .filter(([c, n]) => n > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([c, n]) => ({ key: c, name: data.categories[c] || c, count: n }));
  }, [data]);

  if (!data) {
    return <main className="shell" style={{ paddingTop: 40, textAlign: "center", color: "var(--muted)" }}>Загрузка контент-плана…</main>;
  }

  const withRewrite = data.videos.filter(v => (rewrites[v.id] || []).length).length;

  return (
    <main className="shell" style={{ paddingTop: 20 }}>
      {/* Sub-tabs Импорт / Каталог (по умолчанию открыт Импорт) */}
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        <Chip active={tab === "import"} onClick={() => setTab("import")}>⬇ Импорт канала</Chip>
        <Chip active={tab === "catalog"} onClick={() => setTab("catalog")}>📋 Каталог {data ? `(${data.total})` : ""}</Chip>
      </div>

      {tab === "import" && <ImportForm onImported={() => { setReloadKey(k => k + 1); setTab("catalog"); }} />}
      {tab === "import" && null}

      {tab === "catalog" && <>
      {/* Шапка с фильтрами */}
      <div style={{ ...styles.card, padding: "18px 22px", marginBottom: 20, borderRadius: 16, boxShadow: "0 4px 20px rgba(17,20,15,.04)" }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, ...styles.display, ...styles.ink }}>Контент-план шортсов</h1>
        <div style={{ ...styles.muted, fontSize: 12, marginTop: 6 }}>
          Всего: <b style={styles.ink}>{data.total}</b> · 🔥 залетевшие: <b style={styles.ink}>{data.viral_count}</b> · с рерайтом: <b style={styles.ink}>{withRewrite}</b>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14, alignItems: "center" }}>
          <input type="text" placeholder="Поиск по заголовку и тексту…"
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ ...styles.inset, ...styles.ink, padding: "7px 14px", borderRadius: 999, fontSize: 12, width: 260, ...styles.body, outline: "none" }}
          />
          <Chip active={viralOnly} viral onClick={() => setViralOnly(!viralOnly)}>🔥 Залетевшие</Chip>
          <Chip active={hasRewriteOnly} onClick={() => setHasRewriteOnly(!hasRewriteOnly)}>✏️ С рерайтом</Chip>
          <select value={sort} onChange={e => setSort(e.target.value)}
            style={{ ...styles.inset, ...styles.ink, padding: "7px 12px", borderRadius: 999, fontSize: 12, ...styles.body }}>
            <option value="views">По просмотрам ↓</option>
            <option value="views-asc">По просмотрам ↑</option>
            <option value="title">По названию</option>
          </select>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
          <Chip active={!activeCat} onClick={() => setActiveCat(null)}>
            Все категории <span style={{ marginLeft: 4, opacity: .65 }}>{data.total}</span>
          </Chip>
          {catStats.map(c => (
            <Chip key={c.key} active={activeCat === c.key} onClick={() => setActiveCat(c.key === activeCat ? null : c.key)}>
              {c.name} <span style={{ marginLeft: 4, opacity: .65 }}>{c.count}</span>
            </Chip>
          ))}
        </div>
      </div>

      <div style={{ ...styles.muted, fontSize: 12, marginBottom: 12 }}>
        Показано: <b style={styles.ink}>{filtered.length}</b> из {data.videos.length}
      </div>

      {/* Карточки */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
        {filtered.slice(0, 300).map(v => {
          const rwN = (rewrites[v.id] || []).length;
          return (
            <div key={v.id} style={{
              ...styles.card,
              borderColor: v.is_viral ? "#FFC83D" : "var(--line)",
              borderWidth: v.is_viral ? 2 : 1,
              display: "flex", flexDirection: "column", overflow: "hidden", borderRadius: 12,
              boxShadow: "0 4px 12px rgba(17,20,15,.04)"
            }}>
              <div style={{ position: "relative", aspectRatio: "9/16", background: "#000", maxHeight: 380, overflow: "hidden" }}>
                <img src={v.thumbnail} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                <a href={v.url} target="_blank" rel="noopener" style={{ position: "absolute", inset: 0 }}></a>
                <div style={{ position: "absolute", top: 8, left: 8, ...(v.is_viral ? tone.viral : { background: "rgba(0,0,0,.75)", color: "#fff" }), padding: "3px 8px", borderRadius: 6, fontSize: 11, fontWeight: 700, border: "none" }}>
                  {fmtViews(v.view_count)}{v.is_viral && " 🔥"}
                </div>
              </div>
              <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10, flex: 1 }}>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 600, lineHeight: 1.35, ...styles.ink, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{v.title}</p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {v.categories.map(c => (
                    <span key={c} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10, background: "var(--bg)", color: "var(--muted)", border: "1px solid var(--line)" }}>{data.categories[c] || c}</span>
                  ))}
                </div>
                <button onClick={() => setSelected(v)} disabled={!rwN && !v.transcript}
                  style={{
                    ...(rwN ? tone.accent : tone.chip), ...styles.body,
                    marginTop: "auto", padding: "8px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600,
                    cursor: rwN || v.transcript ? "pointer" : "not-allowed", opacity: (rwN || v.transcript) ? 1 : .45
                  }}>
                  {rwN ? `Открыть рерайты (${rwN})` : v.transcript ? "Открыть оригинал" : "Нет контента"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {filtered.length > 300 && (
        <div style={{ textAlign: "center", padding: 20, color: "var(--muted)", fontSize: 12 }}>Показаны первые 300. Уточни фильтрами или поиском.</div>
      )}

      {selected && (
        <RewriteModal
          video={{ ...selected, transcript: transcripts[selected.id] || "" }}
          rewrites={rewrites}
          categories={data.categories}
          onClose={() => setSelected(null)}
          onRecord={(id, v) => { setSelected(null); onOpenPrompter(id, v); }}
        />
      )}
      </>}
    </main>
  );
}

window.CONTENT_PLAN = { ContentPlanScreen };
