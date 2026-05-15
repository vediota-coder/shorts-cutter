// Modals: Metrics, Brands, Settings — на реальных данных backend.

// helper для компонентов, которые не получают t через props
function _t() {
  return window.I18N[(window.MOCK && window.MOCK.tweaks && window.MOCK.tweaks.lang) || "ru"]
       || window.I18N.ru;
}

// ─────────────────────────────────────────────────────────────────────
// Metrics — /dashboard/all
// ─────────────────────────────────────────────────────────────────────
function MetricsModal({ open, onClose, t }) {
  const { Modal, Icon } = window.UI;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  // первый показ — читает кеш (быстро). Кнопка "Обновить" — pull свежих данных с API.
  const load = React.useCallback((refresh) => {
    setLoading(true); setError("");
    window.API.dashboard(refresh)
      .then((d) => setData(d))
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false));
  }, []);
  const reload = React.useCallback(() => load(true), [load]);

  React.useEffect(() => { if (open) load(false); }, [open, load]);

  const fmt = (n) => Number(n || 0).toLocaleString("ru-RU");
  const rows = data?.rows || [];

  return (
    <Modal open={open} onClose={onClose} title={t.metricsModal} wide>
      <div style={{ marginBottom: 18 }}>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-ghost" onClick={reload} disabled={loading}>
            <Icon name="refresh" size={14}/> {loading ? t.refreshing : t.refreshJob}
          </button>
          {error && <span className="badge-warn">{error}</span>}
          {data && <span className="chip">всего публикаций: {rows.length}</span>}
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: 22 }}>
        <div className="stat">
          <div className="stat-label">{t.totalViews}</div>
          <div className="stat-value">{fmt(data?.total_views)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">{t.likes}</div>
          <div className="stat-value">{fmt(data?.total_likes)}</div>
        </div>
        <div className="stat">
          <div className="stat-label">{t.comments}</div>
          <div className="stat-value">{fmt(data?.total_comments)}</div>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="hint">
          Пока нет опубликованных клипов. Опубликуй хотя бы один клип через таб «Публикация», тогда здесь появятся метрики.
        </div>
      ) : (
        <table className="metrics-table">
          <thead>
            <tr>
              <th style={{ width: "44%" }}>{t.clip}</th>
              <th>{t.metricsBrand}</th>
              <th>VK</th>
              <th>Reels</th>
              <th>Shorts</th>
              <th>TikTok</th>
              <th>{t.metricsTotal}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const m = r.metrics || {};
              const v = {
                vk: m.vk?.views || 0, instagram: m.instagram?.views || 0,
                youtube: m.youtube?.views || 0, tiktok: m.tiktok?.views || 0,
              };
              const total = v.vk + v.instagram + v.youtube + v.tiktok;
              return (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 380 }}>{r.title}</div>
                  </td>
                  <td><span className="chip" style={{ fontSize: 11.5, padding: "3px 8px" }}>{r.brand}</span></td>
                  <td className="mono">{fmt(v.vk)}</td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{fmt(v.instagram)}</td>
                  <td className="mono">{fmt(v.youtube)}</td>
                  <td className="mono" style={{ color: "var(--muted-2)" }}>{v.tiktok ? fmt(v.tiktok) : "—"}</td>
                  <td className="mono" style={{ fontWeight: 700 }}>{fmt(total)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Modal>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Brands — /brands, /brands/{name}, watermark/face/connect
// ─────────────────────────────────────────────────────────────────────
function getPublishPlatformMeta() {
  const t = _t();
  return [
  {
    id: "instagram", name: t.pubInstagramName,
    color: "linear-gradient(135deg, #f58529, #dd2a7b, #8134af)", glyph: "IG",
    hint: t.pubInstagramHint,
    steps: [
      { title: t.instagramStep1Title, body: t.instagramStep1Body },
      { title: "App in Meta for Developers", body: "developers.facebook.com → Create App → Business → product “Instagram Graph API”.", link: "developers.facebook.com" },
      { title: t.instagramStep2Title, body: t.instagramStep2Body },
    ],
    fields: [
      { key: "access_token", label: "Access Token", type: "password" },
      { key: "ig_user_id", label: "Instagram User ID", type: "text" },
      { key: "public_base_url", label: "Public base URL (optional)", type: "text" },
    ],
  },
  {
    id: "vk", name: t.vkAppName,
    color: "linear-gradient(135deg, #4a76a8, #2d5b8b)", glyph: "VK",
    hint: t.pubVkHint,
    steps: [
      { title: t.vkStep1Title, body: t.vkStep1Body },
      { title: t.vkStep2Title, body: t.vkStep2Body },
      { title: "Target Owner ID", body: "0 = personal, negative (-1234) = community." },
    ],
    fields: [
      { key: "access_token", label: "Access Token", type: "password" },
      { key: "target_owner_id", label: "Target Owner ID (0 = personal, -N = community)", type: "number" },
      { key: "target_name", label: t.fieldTargetName, type: "text" },
    ],
  },
  {
    id: "youtube", name: t.pubYoutubeName,
    color: "linear-gradient(135deg, #ff0033, #c4001a)", glyph: "YT",
    hint: t.pubYoutubeHint,
    steps: [
      { title: t.youtubeStep1Title, body: t.youtubeStep1Body, link: "console.cloud.google.com" },
      { title: "OAuth client (Desktop)", body: "Credentials → Create credentials → OAuth client ID → Desktop. Download JSON." },
      { title: t.youtubeStep2Title, body: t.youtubeStep2Body },
    ],
    fields: [],
  },
  {
    id: "tiktok", name: t.pubTiktokName,
    color: "linear-gradient(135deg, #25F4EE, #FE2C55)", glyph: "TT",
    hint: t.pubTiktokHint,
    steps: [
      { title: t.tiktokStep1Title, body: t.tiktokStep1Body },
      { title: t.tiktokStep2Title, body: t.tiktokStep2Body },
      { title: t.tiktokStep3Title, body: t.tiktokStep3Body },
    ],
    fields: [],
  },
  ];
}

function PublishConnect({ platMeta, status, brand, onChanged }) {
  const t = _t();
  const { Icon } = window.UI;
  const [form, setForm] = React.useState({});
  const [loading, setLoading] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [error, setError] = React.useState("");
  const isManual = platMeta.id === "tiktok";

  const submit = async () => {
    setLoading(true); setError("");
    try {
      await window.API.publishConnect(platMeta.id, brand, form);
      setOpen(false);
      onChanged?.();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  // YouTube: загрузка client_secrets.json + старт OAuth flow
  const ytSecretsRef = React.useRef(null);
  const submitYT = async (file) => {
    if (!file) return;
    setLoading(true); setError("");
    try {
      await window.API.uploadYTSecrets(brand, file);
      // после загрузки — сразу запускаем OAuth (откроет браузер для согласия)
      await window.API.publishConnect("youtube", brand);
      setOpen(false);
      onChanged?.();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const disconnect = async () => {
    if (!confirm(`Отключить ${platMeta.name} для бренда ${brand}?`)) return;
    try {
      await window.API.publishDisconnect(platMeta.id, brand);
      onChanged?.();
    } catch (e) {
      setError(e.message || String(e));
    }
  };

  const isConnected = !!status?.connected;

  return (
    <div className="cta-preset" style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: 14 }}>
        <span style={{
          width: 40, height: 40, borderRadius: 10, flexShrink: 0,
          background: platMeta.color, color: "white",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 13, letterSpacing: "-0.02em",
          boxShadow: "0 4px 10px rgba(10,13,10,0.18)",
        }}>{platMeta.glyph}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row" style={{ gap: 8 }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>{platMeta.name}</span>
            {isManual ? <span className="chip" style={{ fontSize: 11, padding: "3px 8px" }}>manual</span> :
              isConnected ? <span className="badge-ok">{t.connected}</span> :
              <span className="badge-warn">{t.pubStatusNotConnected}</span>}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            {isConnected && status?.user_name ? `${status.user_name} · ${status.target_name || ""}`.trim() : platMeta.hint}
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {!isManual && (isConnected
            ? <button className="btn btn-ghost" style={{ padding: "6px 12px", fontSize: 12 }} onClick={disconnect}>{t.disconnect}</button>
            : <button className="btn btn-primary" style={{ padding: "6px 14px", fontSize: 12 }} onClick={() => setOpen(!open)}>{open ? t.close : t.connect}</button>
          )}
          <button
            className="btn btn-ghost"
            onClick={() => setOpen(!open)}
            style={{ padding: "6px 12px", fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            {open ? t.setupHide : t.setupShow}
            <span style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform .15s", display: "inline-flex" }}>
              <Icon name="caret" size={12}/>
            </span>
          </button>
        </div>
      </div>

      {open && (
        <div style={{ padding: "14px 16px 18px 16px", borderTop: "1px solid var(--line-2)", background: "var(--bg-2)" }}>
          {error && <div className="hint" style={{ background: "rgba(224,74,63,0.10)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginBottom: 10 }}>{error}</div>}

          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 10 }}>
            {t.howToSetup}
          </div>
          <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
            {platMeta.steps.map((s, i) => (
              <li key={i} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 12, alignItems: "start" }}>
                <span style={{
                  width: 26, height: 26, borderRadius: 99,
                  background: "var(--ink)", color: "var(--lime)",
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 13,
                }}>{i + 1}</span>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.35 }}>{s.title}</div>
                  <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 3, lineHeight: 1.5 }}>{s.body}</div>
                  {s.link && (
                    <a href={"https://" + s.link} target="_blank" rel="noreferrer" style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      fontSize: 12, fontWeight: 600, marginTop: 6,
                      color: "var(--ink)", textDecoration: "underline", textUnderlineOffset: 3,
                    }}>{s.link} →</a>
                  )}
                </div>
              </li>
            ))}
          </ol>

          {!isConnected && !isManual && platMeta.fields.length > 0 && (
            <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
              {platMeta.fields.map((f) => (
                <div key={f.key}>
                  <label className="label">{f.label}</label>
                  <input
                    className="input mono"
                    type={f.type === "password" ? "password" : (f.type === "number" ? "number" : "text")}
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value })}
                  />
                </div>
              ))}
              <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
                <button className="btn btn-primary" onClick={submit} disabled={loading}>
                  {loading ? t.connecting : t.connect}
                </button>
              </div>
            </div>
          )}

          {/* YouTube: специальная форма — загрузка client_secrets.json */}
          {!isConnected && platMeta.id === "youtube" && (
            <div style={{ marginTop: 14 }}>
              <label className="label">{t.clientSecretsFile}</label>
              <input ref={ytSecretsRef} type="file" hidden accept=".json,application/json" onChange={(e) => submitYT(e.target.files[0])}/>
              <div className="row" style={{ gap: 8 }}>
                <button className="btn btn-ghost" onClick={() => ytSecretsRef.current?.click()} disabled={loading}>
                  <Icon name="upload" size={13}/> {loading ? t.processing : t.uploadJsonOauth}
                </button>
              </div>
              <div className="help">
                После загрузки откроется системный браузер с экраном согласия Google. Дайте доступ и закройте окно — токен сохранится локально.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function BrandIdentityTab({ brand, brandData, onSave }) {
  const t = _t();
  const [form, setForm] = React.useState(brandData || {});
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => { setForm(brandData || {}); }, [brandData?.name]);

  const handle = (k, v) => setForm({ ...form, [k]: v });

  const save = async () => {
    setSaving(true);
    try {
      const patch = {
        niche: form.niche || "",
        audience: form.audience || "",
        voice: form.voice || "",
        lead_url: form.lead_url || "",
      };
      const updated = await window.API.patchBrand(brand, patch);
      onSave?.(updated);
    } catch (e) {
      alert(`Не сохранилось: ${e.message}`);
    } finally { setSaving(false); }
  };

  if (!brandData) return <div style={{ color: "var(--muted)", fontSize: 13 }}>{_t().loadingShort}</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div className="cta-preset" style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{
          width: 56, height: 56, borderRadius: 14,
          background: "var(--ink)", color: "var(--lime)",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          flexShrink: 0, fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 22,
        }}>{(form.name || brand).slice(0, 2).toUpperCase()}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontFamily: "var(--font-display)", fontWeight: 700, fontSize: 22, letterSpacing: "-0.02em" }}>
            {form.name || brand}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 2 }}>
            {form.lead_url ? form.lead_url.replace(/^https?:\/\//, "").split("/")[0] : "—"}
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div>
          <label className="label">{t.leadLink}</label>
          <input className="input mono" style={{ fontSize: 13 }}
            value={form.lead_url || ""}
            onChange={(e) => handle("lead_url", e.target.value)}/>
          <div className="help">{t.leadLinkHelp}</div>
        </div>
        <div>
          <label className="label">{t.niche}</label>
          <input className="input"
            value={form.niche || ""}
            onChange={(e) => handle("niche", e.target.value)}/>
          <div className="help">{t.nicheHelp}</div>
        </div>
      </div>

      <details style={{ borderTop: "1px solid var(--line-2)", paddingTop: 14 }}>
        <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--muted)", listStyle: "none" }}>
          Тонкая настройка для LLM · аудитория · голос
        </summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 14 }}>
          <div>
            <label className="label">{t.audience}</label>
            <input className="input"
              value={form.audience || ""}
              onChange={(e) => handle("audience", e.target.value)}/>
          </div>
          <div>
            <label className="label">{t.voice}</label>
            <textarea className="textarea" style={{ fontFamily: "var(--font-body)", fontSize: 14, minHeight: 88 }}
              value={form.voice || ""}
              onChange={(e) => handle("voice", e.target.value)}/>
          </div>
        </div>
      </details>

      <div className="row" style={{ justifyContent: "flex-end", gap: 8 }}>
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? _t().saving : _t().save}
        </button>
      </div>
    </div>
  );
}

// 9 позиций (3×3 сетка) для watermark/face — top/middle/bottom × left/center/right.
// id'шники должны точно совпадать с WatermarkPos в src/branding.py.
const _POS_GRID = [
  ["top-left",     "top-center",     "top-right"],
  ["middle-left",  "center",         "middle-right"],
  ["bottom-left",  "bottom-center",  "bottom-right"],
];
const _POS_GLYPHS = {
  "top-left": "↖", "top-center": "↑", "top-right": "↗",
  "middle-left": "←", "center": "•", "middle-right": "→",
  "bottom-left": "↙", "bottom-center": "↓", "bottom-right": "↘",
};

function CornerPicker({ value, onChange }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "repeat(3, 28px)", gap: 2,
      padding: 3, borderRadius: 10,
      background: "rgba(255,255,255,0.55)",
      border: "1px solid var(--line)",
      width: "fit-content",
    }}>
      {_POS_GRID.flat().map((id) => {
        const isOn = value === id;
        return (
          <button
            key={id}
            title={id}
            onClick={() => onChange(id)}
            style={{
              width: 28, height: 26, padding: 0,
              borderRadius: 6, border: "none",
              background: isOn ? "var(--ink)" : "transparent",
              color: isOn ? "var(--bg)" : "var(--muted)",
              fontWeight: 700, fontSize: 13, cursor: "pointer",
            }}
          >{_POS_GLYPHS[id]}</button>
        );
      })}
    </div>
  );
}

// Превратить абсолютный путь .../_assets/excella.png → /brand-assets/excella.png
function _assetUrl(absPath) {
  if (!absPath) return null;
  const m = absPath.match(/_assets\/(.+)$/);
  return m ? `/brand-assets/${m[1]}` : null;
}
function _isVideo(absPath) {
  return /\.(mp4|mov|webm|m4v)$/i.test(absPath || "");
}

function BrandOverlaysTab({ brand, brandData, onChanged }) {
  const t = _t();
  const wmRef = React.useRef(null);
  const faceRef = React.useRef(null);
  const [busy, setBusy] = React.useState("");

  if (!brandData) return <div style={{ color: "var(--muted)", fontSize: 13 }}>{_t().loadingShort}</div>;
  const wm = brandData.watermark_path;
  const face = brandData.face_overlay_path;
  const bottom = brandData.bottom_strip;
  const wmUrl = _assetUrl(wm);
  const faceUrl = _assetUrl(face);
  const faceIsVideo = _isVideo(face);

  const setPatch = async (patch) => {
    try {
      await window.API.patchBrand(brand, patch);
      onChanged?.();
    } catch (e) { alert(`Не сохранилось: ${e.message}`); }
  };
  const setPos = (key, value) => setPatch({ [key]: value });

  const upload = async (which, file) => {
    if (!file) return;
    setBusy(which);
    try {
      if (which === "wm") await window.API.uploadWatermark(brand, file);
      else await window.API.uploadFaceOverlay(brand, file);
      onChanged?.();
    } catch (e) {
      alert(`Не загрузилось: ${e.message}`);
    } finally { setBusy(""); }
  };

  // 9 позиций → CSS. bottom_strip есть → авто-отступ снизу для bottom-* и middle-*.
  const bsHeightPct = bottom?.text ? 9 : 0;   // плашка ~9% высоты
  const posStyle = (pos) => {
    const m = "4%";
    const out = { position: "absolute" };
    const v = pos.startsWith("top") ? "top"
      : pos.startsWith("bottom") ? "bottom"
      : "middle";
    const h = pos.endsWith("left") ? "left"
      : pos.endsWith("right") ? "right"
      : "center";
    // вертикальная ось
    if (v === "top") {
      out.top = m;
    } else if (v === "bottom") {
      out.bottom = `calc(${m} + ${bsHeightPct}%)`;
    } else {
      // middle — центрируем относительно области выше плашки
      out.top = `calc(50% - ${bsHeightPct / 2}%)`;
      out.transform = "translateY(-50%)";
    }
    // горизонтальная ось
    if (h === "left") {
      out.left = m;
    } else if (h === "right") {
      out.right = m;
    } else {
      out.left = "50%";
      out.transform = (out.transform || "") + " translateX(-50%)";
    }
    return out;
  };

  // в превью масштаб = scale * 100% от ширины превью (как в реальном рендере)
  const wmW = `${(brandData.watermark_scale || 0.10) * 100}%`;
  const faceW = `${(brandData.face_overlay_scale || 0.22) * 100}%`;
  const wmOpacity = brandData.watermark_opacity ?? 0.7;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: 20, alignItems: "start" }}>
      {/* ── Live превью 9:16 (sticky — следует за скроллом контролов) ── */}
      <div style={{ position: "sticky", top: 8, alignSelf: "start" }}>
        <div style={{
          position: "relative", aspectRatio: "9 / 16",
          borderRadius: 18, overflow: "hidden",
          background: "linear-gradient(180deg, #2b2f36, #0e1014)",
          boxShadow: "0 12px 32px rgba(10,13,10,0.18)",
        }}>
          {/* watermark */}
          {wmUrl && (
            <img
              src={wmUrl}
              alt=""
              style={{
                ...posStyle(brandData.watermark_position || "top-right"),
                width: wmW,
                height: brandData.watermark_height_scale
                  ? `${brandData.watermark_height_scale * 100}%`
                  : "auto",
                objectFit: brandData.watermark_height_scale ? "cover" : undefined,
                opacity: wmOpacity,
                borderRadius: brandData.watermark_radius || 0,
                pointerEvents: "none",
              }}
            />
          )}
          {/* face overlay — img или video в зависимости от типа */}
          {faceUrl && (() => {
            const fStyle = {
              ...posStyle(brandData.face_overlay_position || "bottom-left"),
              width: faceW,
              height: brandData.face_overlay_height_scale
                ? `${brandData.face_overlay_height_scale * 100}%`
                : (brandData.face_overlay_circle ? undefined : "auto"),
              aspectRatio: brandData.face_overlay_height_scale ? undefined
                : (brandData.face_overlay_circle ? "1 / 1" : undefined),
              objectFit: "cover",
              borderRadius: brandData.face_overlay_circle ? "50%" : 12,
              border: "2.5px solid white",
              boxShadow: "0 4px 12px rgba(0,0,0,0.35)",
              pointerEvents: "none",
            };
            return faceIsVideo
              ? <video src={faceUrl} muted loop autoPlay playsInline style={fStyle}/>
              : <img src={faceUrl} alt="" style={fStyle}/>;
          })()}
          {bottom?.text && (() => {
            // backend хранит height/font_size в px на 1920p; в превью пересчитываем в %
            const bsHpct = ((bottom.height || 80) / 1920) * 100;   // % от target_h
            const bsFontPct = ((bottom.font_size || 36) / 1920) * 100;
            return (
              <div style={{
                position: "absolute", left: 0, right: 0, bottom: 0,
                height: `${bsHpct}%`,
                background: bottom.bg_color || "#1E1B4B",
                color: bottom.color || "#FFFFFF",
                opacity: bottom.opacity ?? 0.85,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontFamily: bottom.font_family || "Helvetica Neue",
                fontWeight: bottom.bold ? 700 : 500,
                fontSize: `${bsFontPct}vh`,   // vh approxim. для скейлинга
                letterSpacing: "0.04em",
              }}>{bottom.text}</div>
            );
          })()}
        </div>
        <div style={{ textAlign: "center", fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>
          {_t().preview916} · {wmUrl || faceUrl ? _t().realAssets : _t().uploadAssetsRight}
        </div>
      </div>

      {/* ── Контролы ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Watermark */}
        <div className="cta-preset">
          <div className="row-between" style={{ marginBottom: 8, gap: 12, flexWrap: "wrap" }}>
            <div className="row" style={{ gap: 10, minWidth: 0 }}>
              <span style={{ width: 32, height: 32, background: "var(--ink)", color: "var(--lime)", borderRadius: 8, display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontWeight: 800, fontSize: 11 }}>WM</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>{t.logo}</div>
                <div style={{ fontSize: 11.5, color: "var(--muted)", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {wm ? wm.split("/").pop() : _t().fileNotLoaded}
                </div>
              </div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <input ref={wmRef} type="file" hidden accept="image/*" onChange={(e) => upload("wm", e.target.files[0])}/>
              <button className="btn-link muted" style={{ fontSize: 12 }} onClick={() => wmRef.current?.click()} disabled={busy === "wm"}>
                {busy === "wm" ? "..." : (wm ? _t().replace : _t().upload)}
              </button>
              {wm && (
                <button className="btn-link danger" style={{ fontSize: 12 }} onClick={async () => {
                  if (!confirm(_t().deleteWatermarkConfirm)) return;
                  await fetch(`/brands/${brand}/watermark`, { method: "DELETE" });
                  onChanged?.();
                }}>{t.deleteShort}</button>
              )}
            </div>
          </div>
          {wm && (
            <div style={{ display: "grid", gridTemplateColumns: "auto repeat(auto-fit, minmax(110px, 1fr))", gap: 12, alignItems: "end" }}>
              <div>
                <label className="label">{t.positionLabel}</label>
                <CornerPicker
                  value={brandData.watermark_position || "top-right"}
                  onChange={(v) => setPos("watermark_position", v)}
                />
              </div>
              <div>
                <label className="label">Ширина · {Math.round((brandData.watermark_scale || 0.10) * 100)}%</label>
                <input
                  type="range" min={3} max={50} step={1}
                  value={Math.round((brandData.watermark_scale || 0.10) * 100)}
                  onChange={(e) => setPatch({ watermark_scale: Number(e.target.value) / 100 })}
                  style={{ width: "100%" }}
                />
              </div>
              <div>
                <label className="label">
                  Высота · {brandData.watermark_height_scale
                    ? `${Math.round(brandData.watermark_height_scale * 100)}%`
                    : "auto"}
                </label>
                <input
                  type="range" min={0} max={50} step={1}
                  value={Math.round((brandData.watermark_height_scale || 0) * 100)}
                  onChange={(e) => {
                    const v = Number(e.target.value) / 100;
                    setPatch({ watermark_height_scale: v > 0 ? v : null });
                  }}
                  style={{ width: "100%" }}
                />
              </div>
              <div>
                <label className="label">Скругление · {brandData.watermark_radius || 0}px</label>
                <input
                  type="range" min={0} max={64} step={2}
                  value={brandData.watermark_radius || 0}
                  onChange={(e) => setPatch({ watermark_radius: Number(e.target.value) })}
                  style={{ width: "100%" }}
                />
              </div>
              <div>
                <label className="label">Прозрачность · {Math.round((brandData.watermark_opacity ?? 0.7) * 100)}%</label>
                <input
                  type="range" min={20} max={100} step={5}
                  value={Math.round((brandData.watermark_opacity ?? 0.7) * 100)}
                  onChange={(e) => setPatch({ watermark_opacity: Number(e.target.value) / 100 })}
                  style={{ width: "100%" }}
                />
              </div>
              <div style={{ gridColumn: "1 / -1", marginTop: 8 }}>
                <label className="label" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={!!brandData.watermark_bg_color}
                    onChange={(e) => setPatch({
                      watermark_bg_color: e.target.checked ? (brandData.watermark_bg_color || "#0A0D0A") : null,
                    })}
                  />
                  Подложка под логотипом
                </label>
                {brandData.watermark_bg_color && (
                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr", gap: 12, marginTop: 8, alignItems: "center" }}>
                    <input
                      type="color"
                      value={brandData.watermark_bg_color || "#0A0D0A"}
                      onChange={(e) => setPatch({ watermark_bg_color: e.target.value })}
                      style={{ width: 44, height: 36, padding: 0, border: "1px solid var(--line)", borderRadius: 6, cursor: "pointer" }}
                    />
                    <div>
                      <label className="label" style={{ fontSize: 11 }}>Padding · {brandData.watermark_bg_padding ?? 8}px</label>
                      <input
                        type="range" min={0} max={32} step={2}
                        value={brandData.watermark_bg_padding ?? 8}
                        onChange={(e) => setPatch({ watermark_bg_padding: Number(e.target.value) })}
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <label className="label" style={{ fontSize: 11 }}>Скругление фона · {brandData.watermark_bg_radius ?? 12}px</label>
                      <input
                        type="range" min={0} max={32} step={2}
                        value={brandData.watermark_bg_radius ?? 12}
                        onChange={(e) => setPatch({ watermark_bg_radius: Number(e.target.value) })}
                        style={{ width: "100%" }}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Face overlay */}
        <div className="cta-preset">
          <div className="row-between" style={{ marginBottom: 8, gap: 12, flexWrap: "wrap" }}>
            <div className="row" style={{ gap: 10, minWidth: 0 }}>
              {faceUrl && !faceIsVideo
                ? <img src={faceUrl} style={{ width: 32, height: 32, borderRadius: 99, objectFit: "cover", flexShrink: 0, border: "2px solid white" }}/>
                : faceUrl && faceIsVideo
                  ? <video src={faceUrl} muted loop autoPlay playsInline style={{ width: 32, height: 32, borderRadius: 99, objectFit: "cover", flexShrink: 0, border: "2px solid white" }}/>
                  : <span style={{ width: 32, height: 32, borderRadius: 99, background: "linear-gradient(135deg, #f4d6c1, #b78760)", border: "2px solid white", flexShrink: 0 }}/>
              }
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>
                  Лицо в углу <span style={{ fontWeight: 400, color: "var(--muted)" }}>· для reaction-формата</span>
                </div>
                <div style={{ fontSize: 11.5, color: "var(--muted)", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {face
                    ? `${face.split("/").pop()}${faceIsVideo ? " · видео-цикл" : ""}`
                    : "PNG / JPG (статика) или MP4 / MOV (видео-цикл)"}
                </div>
              </div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <input ref={faceRef} type="file" hidden accept="image/*,video/*,.mp4,.mov,.webm" onChange={(e) => upload("face", e.target.files[0])}/>
              <button className="btn-link muted" style={{ fontSize: 12 }} onClick={() => faceRef.current?.click()} disabled={busy === "face"}>
                {busy === "face" ? "..." : (face ? _t().replace : _t().upload)}
              </button>
              {face && (
                <button className="btn-link danger" style={{ fontSize: 12 }} onClick={async () => {
                  if (!confirm(_t().deleteFaceOverlayConfirm)) return;
                  await fetch(`/brands/${brand}/face-overlay`, { method: "DELETE" });
                  onChanged?.();
                }}>{t.deleteShort}</button>
              )}
            </div>
          </div>
          {face && (
            <div style={{ display: "grid", gridTemplateColumns: "auto repeat(auto-fit, minmax(110px, 1fr)) auto", gap: 12, alignItems: "end" }}>
              <div>
                <label className="label">{t.positionLabel}</label>
                <CornerPicker
                  value={brandData.face_overlay_position || "bottom-left"}
                  onChange={(v) => setPos("face_overlay_position", v)}
                />
              </div>
              <div>
                <label className="label">Ширина · {Math.round((brandData.face_overlay_scale || 0.22) * 100)}%</label>
                <input
                  type="range" min={5} max={60} step={1}
                  value={Math.round((brandData.face_overlay_scale || 0.22) * 100)}
                  onChange={(e) => setPatch({ face_overlay_scale: Number(e.target.value) / 100 })}
                  style={{ width: "100%" }}
                />
              </div>
              <div>
                <label className="label">
                  Высота · {brandData.face_overlay_height_scale
                    ? `${Math.round(brandData.face_overlay_height_scale * 100)}%`
                    : (brandData.face_overlay_circle ? "= ширина" : "auto")}
                </label>
                <input
                  type="range" min={0} max={70} step={1}
                  value={Math.round((brandData.face_overlay_height_scale || 0) * 100)}
                  onChange={(e) => {
                    const v = Number(e.target.value) / 100;
                    setPatch({ face_overlay_height_scale: v > 0 ? v : null });
                  }}
                  style={{ width: "100%" }}
                />
              </div>
              <label className="switch" style={{ alignSelf: "center" }}>
                <span>{t.circle}</span>
                <input type="checkbox" checked={!!brandData.face_overlay_circle} onChange={(e) => setPatch({ face_overlay_circle: e.target.checked })}/>
                <span className="track"></span>
              </label>
            </div>
          )}
        </div>

        {/* Нижняя плашка */}
        <div className="cta-preset">
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>{t.bottomBar}</div>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
            {bottom?.text ? `«${bottom.text}» · ${bottom.bg_color || "#0A0D0A"} / ${bottom.fg_color || "#C6FF3D"}` : _t().barNotConfigured}
          </div>
          {bottom?.text && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
              <div className="grid-2">
                <div>
                  <label className="label">{t.bottomBarText}</label>
                  <input
                    className="input"
                    defaultValue={bottom.text}
                    onBlur={(e) => setPatch({ bottom_strip: { ...bottom, text: e.target.value } })}
                  />
                </div>
                <div>
                  <label className="label">{t.bottomBarFont}</label>
                  <select
                    className="select"
                    value={bottom.font_family || "Helvetica Neue"}
                    onChange={(e) => setPatch({ bottom_strip: { ...bottom, font_family: e.target.value } })}
                  >
                    <option value="Helvetica Neue">Helvetica Neue</option>
                    <option value="Helvetica">Helvetica</option>
                    <option value="Arial">Arial</option>
                    <option value="Inter">Inter</option>
                    <option value="Unbounded">Unbounded</option>
                    <option value="Manrope">Manrope</option>
                    <option value="SF Pro Display">SF Pro Display</option>
                    <option value="Times New Roman">Times New Roman</option>
                    <option value="Georgia">Georgia</option>
                  </select>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
                <div>
                  <label className="label">Размер шрифта · {bottom.font_size || 36}pt</label>
                  <input
                    type="range" min={16} max={96} step={2}
                    value={bottom.font_size || 36}
                    onChange={(e) => setPatch({ bottom_strip: { ...bottom, font_size: Number(e.target.value) } })}
                    style={{ width: "100%" }}
                  />
                </div>
                <div>
                  <label className="label">Высота плашки · {bottom.height || 80}px</label>
                  <input
                    type="range" min={40} max={200} step={4}
                    value={bottom.height || 80}
                    onChange={(e) => setPatch({ bottom_strip: { ...bottom, height: Number(e.target.value) } })}
                    style={{ width: "100%" }}
                  />
                </div>
                <div>
                  <label className="label">Прозрачность · {Math.round((bottom.opacity ?? 0.85) * 100)}%</label>
                  <input
                    type="range" min={30} max={100} step={5}
                    value={Math.round((bottom.opacity ?? 0.85) * 100)}
                    onChange={(e) => setPatch({ bottom_strip: { ...bottom, opacity: Number(e.target.value) / 100 } })}
                    style={{ width: "100%" }}
                  />
                </div>
              </div>

              <div className="row" style={{ gap: 10 }}>
                <div style={{ flex: 1 }}>
                  <label className="label">{t.bottomBarBg}</label>
                  <div className="row" style={{ gap: 6 }}>
                    <input type="color" value={bottom.bg_color || "#1E1B4B"} onChange={(e) => setPatch({ bottom_strip: { ...bottom, bg_color: e.target.value.toUpperCase() } })} style={{ width: 40, height: 36, border: "none", padding: 0 }}/>
                    <input className="input mono" style={{ fontSize: 12 }} value={bottom.bg_color || "#1E1B4B"} onChange={(e) => setPatch({ bottom_strip: { ...bottom, bg_color: e.target.value } })}/>
                  </div>
                </div>
                <div style={{ flex: 1 }}>
                  <label className="label">{t.bottomBarFg}</label>
                  <div className="row" style={{ gap: 6 }}>
                    <input type="color" value={bottom.color || "#FFFFFF"} onChange={(e) => setPatch({ bottom_strip: { ...bottom, color: e.target.value.toUpperCase() } })} style={{ width: 40, height: 36, border: "none", padding: 0 }}/>
                    <input className="input mono" style={{ fontSize: 12 }} value={bottom.color || "#FFFFFF"} onChange={(e) => setPatch({ bottom_strip: { ...bottom, color: e.target.value } })}/>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function BrandsModal({ open, onClose, t, brand, setBrand }) {
  const { Modal, Icon } = window.UI;
  const [tab, setTab] = React.useState("identity");
  const [brands, setBrands] = React.useState([]);
  const [brandData, setBrandData] = React.useState(null);
  const [pubStatuses, setPubStatuses] = React.useState({});

  const reloadBrands = React.useCallback(async () => {
    try {
      const list = await window.API.brands();
      setBrands(list || []);
    } catch (e) { /* silent */ }
  }, []);

  const reloadBrandDetail = React.useCallback(async () => {
    if (!brand) return;
    try { setBrandData(await window.API.brand(brand)); }
    catch { setBrandData(null); }
  }, [brand]);

  const reloadPublishStatuses = React.useCallback(async () => {
    if (!brand) return;
    const [ig, vk, yt] = await Promise.all([
      window.API.publishStatus("instagram", brand).catch(() => ({})),
      window.API.publishStatus("vk", brand).catch(() => ({})),
      window.API.publishStatus("youtube", brand).catch(() => ({})),
    ]);
    setPubStatuses({ instagram: ig, vk, youtube: yt });
  }, [brand]);

  React.useEffect(() => {
    if (open) { reloadBrands(); reloadBrandDetail(); reloadPublishStatuses(); }
  }, [open, brand, reloadBrands, reloadBrandDetail, reloadPublishStatuses]);

  const createNew = async () => {
    const name = prompt(_t().newBrandPrompt);
    if (!name) return;
    try {
      await window.API.createBrand({ name, copy_from: brand });
      await reloadBrands();
      setBrand(name);
    } catch (e) { alert(`Не создано: ${e.message}`); }
  };

  const removeBrand = async () => {
    if (!confirm(`Удалить бренд ${brand}? Активный бренд переключится на первый из оставшихся.`)) return;
    try {
      await window.API.deleteBrand(brand);
      const list = await window.API.brands();
      setBrands(list || []);
      setBrand(list?.[0]?.name || "");
    } catch (e) { alert(`Не удалено: ${e.message}`); }
  };

  return (
    <Modal open={open} onClose={onClose} title={t.brandsTitle} wide>
      <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 20 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 8 }}>
            {t.brands}
          </div>
          <div className="brand-list">
            {brands.map((b) => (
              <button
                key={b.name}
                className={"brand-item " + (brand === b.name ? "active" : "")}
                onClick={() => setBrand(b.name)}
              >
                {b.name}
              </button>
            ))}
          </div>
          <button className="btn btn-ghost" style={{ marginTop: 10, width: "100%", justifyContent: "center" }} onClick={createNew}>
            <Icon name="plus" size={14}/> {t.newBrand}
          </button>
          {brands.length > 1 && (
            <button className="btn-link danger" style={{ marginTop: 8, fontSize: 12, width: "100%", textAlign: "center" }} onClick={removeBrand}>
              удалить «{brand}»
            </button>
          )}
        </div>

        <div>
          <div className="text-tabs">
            {[
              ["identity", _t().brandTabIdentity],
              ["overlays", _t().brandTabOverlays],
              ["cta", "CTA"],
              ["pronunciation", _t().brandTabPronunciation],
              ["publish", _t().brandTabPublish],
            ].map(([k, label]) => (
              <button key={k} className={"text-tab " + (tab === k ? "active" : "")} onClick={() => setTab(k)}>
                {label}
              </button>
            ))}
          </div>

          {tab === "identity" && (
            <BrandIdentityTab brand={brand} brandData={brandData} onSave={(updated) => { setBrandData(updated); reloadBrands(); }}/>
          )}

          {tab === "overlays" && (
            <BrandOverlaysTab brand={brand} brandData={brandData} onChanged={reloadBrandDetail}/>
          )}

          {tab === "cta" && (
            <BrandCtaTab brand={brand} brandData={brandData} onChanged={reloadBrandDetail} t={t}/>
          )}

          {tab === "pronunciation" && (
            <BrandPronunciationTab brand={brand} brandData={brandData} onChanged={reloadBrandDetail}/>
          )}

          {tab === "publish" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {getPublishPlatformMeta().map((meta) => (
                <PublishConnect
                  key={meta.id}
                  platMeta={meta}
                  status={pubStatuses[meta.id] || {}}
                  brand={brand}
                  onChanged={reloadPublishStatuses}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

function BrandCtaTab({ brand, brandData, onChanged, t }) {
  const { Icon } = window.UI;
  const [saving, setSaving] = React.useState(false);
  const [list, setList] = React.useState([]);

  React.useEffect(() => {
    if (!brandData) return;
    const items = Object.entries(brandData.cta_presets || {}).map(([key, v]) => ({
      key, text: v.text || "", sub_text: v.sub_text || "",
    }));
    setList(items);
  }, [brandData?.name]);

  const updateItem = (i, field, v) => {
    const next = [...list];
    next[i] = { ...next[i], [field]: v };
    setList(next);
  };

  const removeItem = (i) => setList(list.filter((_, j) => j !== i));

  const addItem = () => {
    const key = prompt(_t().brandNewCtaPrompt);
    if (!key) return;
    setList([...list, { key, text: "", sub_text: "" }]);
  };

  const save = async () => {
    setSaving(true);
    try {
      const cta_presets = Object.fromEntries(list.map((c) => [c.key, { text: c.text, sub_text: c.sub_text }]));
      const updated = await window.API.patchBrand(brand, { cta_presets });
      onChanged?.(updated);
      alert("CTA сохранены");
    } catch (e) { alert(`Не сохранилось: ${e.message}`); }
    finally { setSaving(false); }
  };

  if (!brandData) return <div style={{ color: "var(--muted)", fontSize: 13 }}>{_t().loadingShort}</div>;
  return (
    <div>
      <div className="row-between" style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Эти варианты появляются как кнопки на главном экране. Дефолт — <strong>{brandData.cta_default || list[0]?.key || "—"}</strong>.
        </div>
        <button className="btn btn-ghost" onClick={addItem}><Icon name="plus" size={14}/> добавить</button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {list.map((c, i) => (
          <div key={i} className="cta-preset" style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr auto", gap: 10, alignItems: "center" }}>
            <span className="chip" style={{ minWidth: 70, justifyContent: "center" }}>{c.key}</span>
            <input className="input" value={c.text} onChange={(e) => updateItem(i, "text", e.target.value)} placeholder={_t().brandCtaText}/>
            <input className="input mono" style={{ fontSize: 13 }} value={c.sub_text} onChange={(e) => updateItem(i, "sub_text", e.target.value)} placeholder="URL / приписка"/>
            <button className="btn-link danger" onClick={() => removeItem(i)}>{_t().deleteShort}</button>
          </div>
        ))}
      </div>
      <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
        <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? _t().saving : _t().save}</button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Settings — /prompts, /settings, /improvement/stats + Стили субтитров
// ─────────────────────────────────────────────────────────────────────
function SettingsModal({ open, onClose, t }) {
  const { Modal, Icon } = window.UI;
  const [tab, setTab] = React.useState("prompts");

  return (
    <Modal open={open} onClose={onClose} title={t.settingsTitle} wide>
      <div className="text-tabs">
        {[
          ["prompts", _t().settingsTabPrompts],
          ["styles", _t().settingsTabStyles],
          ["pexels", "Pexels API"],
          ["hf", "HuggingFace"],
          ["elevenlabs", "ElevenLabs 🎙"],
          ["stats", _t().settingsTabStats],
        ].map(([k, label]) => (
          <button key={k} className={"text-tab " + (tab === k ? "active" : "")} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "prompts" && <PromptsTab onClose={onClose} t={t}/>}
      {tab === "styles" && <SubtitleStylesTab open={open}/>}
      {tab === "pexels" && <PexelsTab/>}
      {tab === "hf" && <HfTab/>}
      {tab === "elevenlabs" && <ElevenLabsTab/>}
      {tab === "stats" && <StatsTab/>}
    </Modal>
  );
}

function PromptsTab({ onClose, t }) {
  const { Icon } = window.UI;
  const [prompts, setPrompts] = React.useState([]);
  const [edits, setEdits] = React.useState({});
  const [saving, setSaving] = React.useState("");

  const reload = React.useCallback(async () => {
    try {
      const arr = await window.API.prompts();
      setPrompts(arr);
      setEdits(Object.fromEntries(arr.map((p) => [p.name, p.text])));
    } catch {}
  }, []);

  React.useEffect(() => { reload(); }, [reload]);

  const save = async (name) => {
    setSaving(name);
    try {
      await window.API.savePrompt(name, edits[name]);
      await reload();
    } catch (e) { alert(`Не сохранилось: ${e.message}`); }
    finally { setSaving(""); }
  };

  const reset = async (name) => {
    if (!confirm(_t().settingsResetPromptConfirm)) return;
    try {
      const r = await window.API.resetPrompt(name);
      setEdits((e) => ({ ...e, [name]: r.text }));
      await reload();
    } catch (e) { alert(`Не сбросилось: ${e.message}`); }
  };

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>
        System-промпты для выбора моментов и SEO-метаданных. Меняй под свою нишу/голос.
      </div>
      {prompts.map((p) => (
        <div key={p.name} style={{ marginBottom: 18 }}>
          <div className="label-row">
            <label className="label">{p.label} {p.customized && <span className="badge-warn" style={{ background: "rgba(198,255,61,0.18)", color: "var(--ink-2)" }}>{_t().customizedBadge}</span>}</label>
            <button className="btn-link muted" onClick={() => reset(p.name)}>
              <Icon name="refresh" size={12}/> сбросить
            </button>
          </div>
          <textarea
            className="textarea"
            style={{ minHeight: 180 }}
            value={edits[p.name] || ""}
            onChange={(e) => setEdits({ ...edits, [p.name]: e.target.value })}
          />
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 8, gap: 8 }}>
            <button className="btn btn-primary" onClick={() => save(p.name)} disabled={saving === p.name}>
              {saving === p.name ? _t().saving : _t().save}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── СТИЛИ СУБТИТРОВ — расширяемая вкладка ──
const _BUILTIN_KEYS = ["karaoke", "block", "minimal", "neon", "telegram", "big_white"];

function SubtitleStylesTab({ open }) {
  const { Icon } = window.UI;
  const [list, setList] = React.useState([]);
  const [editing, setEditing] = React.useState(null);
  const [draft, setDraft] = React.useState({});
  const [saving, setSaving] = React.useState(false);

  const reload = React.useCallback(async () => {
    try { setList(await window.API.subtitleTemplates()); }
    catch {}
  }, []);

  React.useEffect(() => { if (open) reload(); }, [open, reload]);

  const startEdit = (s) => {
    setEditing(s.key);
    setDraft({ ...s });
  };

  const createNew = async () => {
    const key = prompt(_t().settingsNewStylePrompt1, _t().settingsNewStylePromptDefault);
    if (!key) return;
    const copy_from = prompt(`На основе какого пресета? (${list.map(l => l.key).join(", ")})`, "block");
    if (!copy_from) return;
    const name = prompt(_t().settingsNewStyleNamePrompt, `✨ ${key}`);
    try {
      const created = await window.API.createSubtitleTemplate({ key, copy_from, name });
      await reload();
      // сразу открываем для редактирования
      startEdit(created);
    } catch (e) { alert(`Не создано: ${e.message}`); }
  };

  const deleteCustom = async (key) => {
    if (_BUILTIN_KEYS.includes(key)) {
      alert(_t().settingsBuiltinAlert);
      return;
    }
    if (!confirm(`Удалить кастомный стиль ${key}?`)) return;
    try {
      await window.API.deleteSubtitleTemplate(key);
      await reload();
      if (editing === key) setEditing(null);
    } catch (e) { alert(`Не удалилось: ${e.message}`); }
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const patch = { ...draft };
      delete patch.key;
      await window.API.patchSubtitleTemplate(editing, patch);
      await reload();
      // обновляем глобальный MOCK так чтобы CutForm увидел новые параметры стиля
      const fresh = await window.API.subtitleTemplates();
      window.MOCK.SUBTITLE_STYLES = fresh.map((tpl) => ({
        id: tpl.key, name: tpl.name,
        kind: tpl.use_highlight ? "karaoke" : "block",
        words: tpl.words_per_chunk, pt: tpl.size,
      }));
      setEditing(null);
    } catch (e) { alert(`Не сохранилось: ${e.message}`); }
    finally { setSaving(false); }
  };

  const reset = async (key) => {
    if (!confirm(_t().settingsResetCustomConfirm)) return;
    try {
      await window.API.resetSubtitleTemplate(key);
      await reload();
      if (editing === key) setEditing(null);
    } catch (e) { alert(`Не сбросилось: ${e.message}`); }
  };

  return (
    <div>
      <div className="row-between" style={{ marginBottom: 14, alignItems: "flex-start", gap: 14 }}>
        <div style={{ fontSize: 13, color: "var(--muted)", flex: 1 }}>
          Стили субтитров — параметры ASS-файла, который прожигается в видео. Изменения сохраняются на диск и переживают рестарт.
          Превью — приближённое; реальный рендер делает ffmpeg на финальном кадре 9:16.
        </div>
        <button className="btn btn-primary" onClick={createNew} style={{ flexShrink: 0 }}>
          <Icon name="plus" size={13}/> создать стиль
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
        {list.map((s) => (
          <div key={s.key} style={{
            padding: 12, borderRadius: 14,
            border: editing === s.key ? "2px solid var(--lime-2)" : "1px solid var(--line)",
            background: "var(--bg-3)",
            display: "flex", flexDirection: "column", gap: 10,
          }}>
            <div style={{
              height: 88, borderRadius: 10,
              background: "linear-gradient(180deg, #2b2f36 0%, #1a1d23 60%, #0c0e12 100%)",
              position: "relative", display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 12,
            }}>
              <span style={{
                fontFamily: s.font || "var(--font-display)",
                fontWeight: s.bold ? 800 : 500,
                fontSize: Math.min(20, (s.size || 48) / 3),
                color: s.color || "white",
                textShadow: `0 0 ${s.outline}px ${s.outline_color || "#000"}`,
                background: s.use_highlight ? `linear-gradient(180deg, transparent 55%, ${s.highlight} 55%)` : "transparent",
                padding: "2px 6px", borderRadius: 3,
              }}>
                момент
              </span>
            </div>
            <div className="row-between">
              <div style={{ fontSize: 13, fontWeight: 700 }}>{s.name}</div>
              <span className="chip" style={{ fontSize: 10.5, padding: "2px 8px" }}>{s.size}pt</span>
            </div>
            <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--font-mono)" }}>
              {s.words_per_chunk}w · adv {s.chunk_advance} · margin {s.margin_v}
            </div>
            <div className="row" style={{ gap: 6 }}>
              <button className="btn btn-ghost" style={{ flex: 1, padding: "6px 10px", fontSize: 12, justifyContent: "center" }} onClick={() => startEdit(s)}>
                редактировать
              </button>
              {_BUILTIN_KEYS.includes(s.key)
                ? <button className="btn-link muted" style={{ fontSize: 11 }} onClick={() => reset(s.key)}>{_t().resetShort}</button>
                : <button className="btn-link danger" style={{ fontSize: 11 }} onClick={() => deleteCustom(s.key)}>{_t().deleteShort}</button>
              }
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <div className="glass-soft" style={{ marginTop: 18, padding: 16 }}>
          <div className="row-between" style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>Редактирование: {draft.name || editing}</div>
            <button className="btn-link muted" onClick={() => setEditing(null)}>{_t().cancelShort}</button>
          </div>
          <div className="grid-3">
            {[
              ["size", _t().styleFieldSize, "number"],
              ["bold", _t().styleFieldBold, "bool"],
              ["color", _t().styleFieldColor, "color"],
              ["highlight", _t().styleFieldHighlight, "color"],
              ["outline_color", _t().styleFieldOutlineColor, "color"],
              ["outline", _t().styleFieldOutline, "number"],
              ["shadow", _t().styleFieldShadow, "number"],
              ["margin_v", "Margin V (px)", "number"],
              ["words_per_chunk", _t().styleFieldWordsPerChunk, "number"],
              ["chunk_advance", _t().styleFieldChunkAdvance, "number"],
              ["max_chars_per_line", _t().styleFieldMaxChars, "number"],
              ["use_highlight", _t().styleFieldUseHighlight, "bool"],
              ["min_chunk_duration", _t().styleFieldMinChunkDur, "number"],
              ["highlight_scale", "Scale хайлайта (%)", "number"],
            ].map(([k, label, type]) => (
              <div key={k}>
                <label className="label">{label}</label>
                {type === "bool" ? (
                  <label className="switch">
                    <input type="checkbox" checked={!!draft[k]} onChange={(e) => setDraft({ ...draft, [k]: e.target.checked })}/>
                    <span className="track"></span>
                  </label>
                ) : type === "color" ? (
                  <div className="row" style={{ gap: 6 }}>
                    <input type="color" value={draft[k] || "#FFFFFF"} onChange={(e) => setDraft({ ...draft, [k]: e.target.value.toUpperCase() })} style={{ width: 40, height: 36, border: "none", padding: 0 }}/>
                    <input className="input mono" style={{ fontSize: 12 }} value={draft[k] || ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}/>
                  </div>
                ) : (
                  <input
                    className="input mono"
                    type={type}
                    step={k === "min_chunk_duration" ? "0.1" : "1"}
                    value={draft[k] ?? ""}
                    onChange={(e) => setDraft({ ...draft, [k]: type === "number" ? Number(e.target.value) : e.target.value })}
                  />
                )}
              </div>
            ))}
          </div>
          <div className="row" style={{ justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
            <button className="btn btn-ghost" onClick={() => setEditing(null)}>{_t().cancel}</button>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? _t().saving : _t().save}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function BrandPronunciationTab({ brand, brandData, onChanged }) {
  const initial = (brandData && brandData.pronunciations) || {};
  const [pairs, setPairs] = React.useState(
    Object.entries(initial).map(([k, v]) => ({ k, v }))
  );
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setPairs(Object.entries((brandData && brandData.pronunciations) || {}).map(([k, v]) => ({ k, v })));
  }, [brandData]);

  const update = (i, field, val) => {
    setPairs((arr) => arr.map((p, idx) => (idx === i ? { ...p, [field]: val } : p)));
  };
  const add = () => setPairs((arr) => [...arr, { k: "", v: "" }]);
  const remove = (i) => setPairs((arr) => arr.filter((_, idx) => idx !== i));

  const save = async () => {
    setSaving(true);
    try {
      const dict = {};
      for (const { k, v } of pairs) {
        const key = (k || "").trim();
        const val = (v || "").trim();
        if (key && val) dict[key] = val;
      }
      await window.API.patchBrand(brand, { pronunciations: dict });
      onChanged?.();
    } catch (e) {
      alert(_t().saveFailed + " " + e.message);
    } finally {
      setSaving(false);
    }
  };

  const insertStress = (i) => {
    const el = document.getElementById(`pron-v-${i}`);
    if (!el) return;
    const start = el.selectionStart || 0;
    const before = pairs[i].v.slice(0, start);
    const after = pairs[i].v.slice(start);
    update(i, "v", before + "́" + after);
    setTimeout(() => el.focus(), 10);
  };

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14, lineHeight: 1.6 }}>
        Замены для TTS-озвучки. Каждое вхождение слова из левой колонки в озвучке заменяется
        на правую (с алиасом-ударением). Полезно для имён, брендов, аббревиатур, чисел.
        <br/>
        <strong>Ударение</strong>: символ <code>́</code> (combining acute, U+0301) ставится <em>после</em> ударной
        гласной — например, <code>догово́р</code>. Кнопка <code>́</code> вставляет в позицию курсора.
      </div>

      {pairs.map((p, i) => (
        <div key={i} className="row" style={{ gap: 8, marginBottom: 6, alignItems: "center" }}>
          <input
            className="input mono"
            placeholder="Excella"
            value={p.k}
            onChange={(e) => update(i, "k", e.target.value)}
            style={{ flex: 1, fontSize: 13 }}
          />
          <span style={{ color: "var(--muted)" }}>→</span>
          <input
            id={`pron-v-${i}`}
            className="input mono"
            placeholder={_t().brandStressPlaceholder}
            value={p.v}
            onChange={(e) => update(i, "v", e.target.value)}
            style={{ flex: 1.4, fontSize: 13 }}
          />
          <button type="button" className="btn" style={{ padding: "4px 8px", fontSize: 11 }}
                  onClick={() => insertStress(i)} title={_t().brandStressInsert}>
            ́
          </button>
          <button type="button" className="btn-link danger" onClick={() => remove(i)}>×</button>
        </div>
      ))}

      <div className="row" style={{ marginTop: 12, gap: 8, justifyContent: "space-between" }}>
        <button type="button" className="btn btn-ghost" onClick={add}>+ добавить</button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? _t().saving : `${_t().save} (${pairs.filter(p => p.k && p.v).length})`}
        </button>
      </div>
    </div>
  );
}


function PexelsTab() {
  const [data, setData] = React.useState(null);
  const [val, setVal] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  const reload = () => window.API.settings().then(setData);
  React.useEffect(() => { reload(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await window.API.saveSettings({ pexels_api_key: val });
      setVal("");
      await reload();
    } finally { setSaving(false); }
  };

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>
        Ключ для поиска стоковых видео-вставок (B-roll). Получить: pexels.com/api — бесплатно, 200 запросов в час.
      </div>
      <label className="label">API key</label>
      <div className="row" style={{ gap: 8 }}>
        <input className="input mono" value={val} placeholder={data?.pexels_set ? `${_t().pexelsKeyCurrent} ${data.pexels_masked || "••••"}` : _t().pexelsKeyPlaceholder} onChange={(e) => setVal(e.target.value)}/>
        {data?.pexels_set && <span className="badge-ok" style={{ flexShrink: 0 }}>{_t().installed}</span>}
        <button className="btn btn-primary" onClick={save} disabled={!val || saving}>{saving ? "..." : _t().saveShort}</button>
      </div>
    </div>
  );
}

function HfTab() {
  const [data, setData] = React.useState(null);
  const [val, setVal] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");

  const reload = () => window.API.settings().then(setData);
  React.useEffect(() => { reload(); }, []);

  const save = async () => {
    setSaving(true); setError("");
    try {
      await window.API.saveSettings({ hf_token: val });
      setVal("");
      await reload();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>
        Нужен, чтобы быстро скачивать модели Whisper. Без токена ~1 MB/s, с токеном — 10+ MB/s. Бесплатно.
      </div>
      <label className="label">Token</label>
      <div className="row" style={{ gap: 8 }}>
        <input className="input mono" placeholder={data?.hf_token_set ? `текущий: ${data.hf_token_masked || "••••"}` : "hf_•••••••••••••••••••••••••••"} value={val} onChange={(e) => setVal(e.target.value)}/>
        {data?.hf_token_set && <span className="badge-ok" style={{ flexShrink: 0 }}>{_t().installed}</span>}
        <button className="btn btn-primary" onClick={save} disabled={!val || saving}>{saving ? "..." : _t().saveShort}</button>
      </div>
      {error && <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginTop: 12 }}>{error}</div>}
    </div>
  );
}

function ElevenLabsTab() {
  const t = _t();
  const [data, setData] = React.useState(null);
  const [val, setVal] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [probe, setProbe] = React.useState(null);
  const [probing, setProbing] = React.useState(false);

  const reload = () => window.API.settings().then(setData);
  React.useEffect(() => { reload(); }, []);

  const save = async (value) => {
    setSaving(true); setError(""); setProbe(null);
    try {
      await window.API.saveSettings({ elevenlabs_api_key: value });
      setVal("");
      await reload();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  const check = async () => {
    setProbing(true); setProbe(null);
    try {
      const r = await window.API.elevenlabsCheck();
      setProbe(r);
    } catch (e) { setProbe({ ok: false, error: e.message }); }
    finally { setProbing(false); }
  };

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>
        Ключ для синтеза речи и Dubbing API. Получить:{" "}
        <a href="https://elevenlabs.io/app/settings/api-keys" target="_blank" rel="noreferrer"
           style={{ color: "var(--ink)", textDecoration: "underline" }}>
          elevenlabs.io/app/settings/api-keys
        </a>.
        Free план — TTS до 10к симв/мес. Для clone-дубляжа (голос оригинала) нужен Pro ($99/мес).
      </div>

      <details style={{ marginBottom: 14, padding: 12, background: "var(--paper-2)", borderRadius: 8, fontSize: 13 }}>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>{t.elevenHowToTitle}</summary>
        <ol style={{ marginTop: 10, paddingLeft: 20, lineHeight: 1.7, color: "var(--ink-2)" }}>
          <li>{t.elevenStep1Pre} <a href="https://elevenlabs.io" target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>elevenlabs.io</a> {t.elevenStep1Post}</li>
          <li>{t.elevenStep2Pre} <a href="https://elevenlabs.io/app/settings/api-keys" target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>Settings → API Keys</a> {t.elevenStep2Mid} <b>Create API Key</b>.</li>
          <li>{t.elevenStep3} <code>sk_…</code> {t.elevenStep3Post}</li>
        </ol>
        <div style={{ marginTop: 8, color: "var(--muted)" }}>
          Хранится локально в <code>.env</code>, никуда не уходит. Кнопка «Проверить» делает probe-запрос
          к API и показывает план + доступ к Dubbing API.
        </div>
      </details>

      <label className="label">API key</label>
      <div className="row" style={{ gap: 8 }}>
        <input className="input mono" type="password"
               placeholder={data?.elevenlabs_set ? `текущий: ${data.elevenlabs_masked || "••••"}` : "sk_•••••••••••••••••••••••••••"}
               value={val} onChange={(e) => setVal(e.target.value)}/>
        {data?.elevenlabs_set && <span className="badge-ok" style={{ flexShrink: 0 }}>{_t().installed}</span>}
        <button className="btn" onClick={check} disabled={!data?.elevenlabs_set || probing}>
          {probing ? "..." : _t().probeBtn}
        </button>
        {data?.elevenlabs_set && (
          <button className="btn" onClick={() => save("")} disabled={saving}>{t.deleteShort}</button>
        )}
        <button className="btn btn-primary" onClick={() => save(val)} disabled={!val || saving}>
          {saving ? "..." : _t().saveShort}
        </button>
      </div>

      {error && (
        <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginTop: 12 }}>
          {error}
        </div>
      )}

      {probe && (
        probe.ok ? (
          <div style={{ marginTop: 14, padding: 12, background: "var(--paper-2)", borderRadius: 8, fontSize: 13, lineHeight: 1.7 }}>
            <div>✅ ключ работает</div>
            {probe.user_scope ? (
              <>
                <div>{t.elevenPlan} <b>{probe.tier}</b></div>
                <div>использовано: {probe.characters_used.toLocaleString()} / {probe.characters_limit.toLocaleString()} симв</div>
              </>
            ) : (
              <div style={{ color: "var(--muted)" }}>
                ⓘ scope <code>user_read</code> не выдан — план/баланс посмотри в{" "}
                <a href="https://elevenlabs.io/app/usage" target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>
                  Dashboard → Usage
                </a>
              </div>
            )}
            <div style={{
              color: probe.dubbing === "available" ? "var(--green)"
                   : probe.dubbing === "no_scope" ? "var(--muted)"
                   : "var(--danger)"
            }}>
              {probe.dubbing === "available" && "✅ Dubbing API доступен (clone-режим работает)"}
              {probe.dubbing === "no_scope" && (
                <>⚠ scope <code>dubbing_read/write</code> не выдан — clone-режим не заработает.
                Перевыпусти ключ с правами Dubbing.</>
              )}
              {probe.dubbing === "no_plan" && "⚠ Dubbing API недоступен на текущем плане — нужен Pro+. Library-режим работает."}
              {probe.dubbing === "unknown" && "? статус Dubbing API определить не удалось — попробуй clone и смотри лог job'а"}
            </div>
          </div>
        ) : (
          <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)", marginTop: 12 }}>
            ✗ {probe.error || _t().probeFailed}
          </div>
        )
      )}
    </div>
  );
}

function StatsTab() {
  const t = _t();
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    window.API.improvementStats().then(setData).catch((e) => setError(e.message));
  }, []);
  if (error) return <div className="hint" style={{ background: "rgba(224,74,63,0.1)", borderColor: "rgba(224,74,63,0.4)", color: "var(--danger)" }}>{error}</div>;
  if (!data) return <div style={{ color: "var(--muted)", fontSize: 13 }}>загружаю…</div>;
  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>
        Анализ ваших правок Smart reframe — где classifier чаще всего ошибается. На основе паттернов даём подсказки по тюнингу.
      </div>
      <div className="grid-3" style={{ marginBottom: 18 }}>
        <div className="stat">
          <div className="stat-label">{t.statsTotalCorrections}</div>
          <div className="stat-value">{data.total_corrections || 0}</div>
        </div>
        <div className="stat">
          <div className="stat-label">{t.statsMostCommon}</div>
          <div className="stat-value" style={{ fontSize: 18 }}>
            {data.most_common_correction || "—"}
          </div>
        </div>
        <div className="stat">
          <div className="stat-label">{t.statsTotalJobs}</div>
          <div className="stat-value">{data.total_jobs || 0}</div>
        </div>
      </div>
      {data.suggestions?.length > 0 && (
        <div className="cta-preset">
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 8 }}>{t.statsTuningHints}</div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--muted)", lineHeight: 1.55 }}>
            {data.suggestions.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

window.MODALS = { MetricsModal, BrandsModal, SettingsModal };
