// Mock state for the prototype.
// Имена синхронизированы с src/subtitles.py PRESETS (включая emoji), чтобы не было
// flash при первой загрузке пока бекенд отдаст актуальные данные.
// id'шники должны точно совпадать с backend keys (big_white, не bigwhite).
const SUBTITLE_STYLES = [
  { id: "karaoke",   name: "🎤 Karaoke (TikTok)", kind: "karaoke", words: 3, pt: 58 },
  { id: "block",     name: "📦 Block (фразы)",    kind: "block",   words: 3, pt: 56 },
  { id: "minimal",   name: "✏️ Minimal",          kind: "block",   words: 3, pt: 44 },
  { id: "neon",      name: "🌈 Neon",             kind: "karaoke", words: 3, pt: 64 },
  { id: "telegram",  name: "✈️ Telegram",         kind: "block",   words: 6, pt: 42 },
  { id: "big_white", name: "⚪ Big White",        kind: "block",   words: 2, pt: 66 },
];

const LLM_PROVIDERS = [
  { id: "claude_code", name: "Claude Code", sub: "подписка Pro/Max", configured: true, badge: "💳 подписка" },
  { id: "openai_codex", name: "OpenAI Codex CLI", sub: "подписка ChatGPT Plus/Pro", configured: true, badge: "💳 подписка" },
  { id: "gemini_cli", name: "Gemini CLI", sub: "Google аккаунт / Gemini Advanced", configured: true, badge: "💳 подписка" },
  { id: "anthropic_api", name: "Anthropic API", sub: "платно по токенам", configured: false, badge: "🔑 API" },
  { id: "openai_api", name: "OpenAI API", sub: "платно по токенам", configured: false, badge: "🔑 API" },
  { id: "gemini_api", name: "Google Gemini API", sub: "есть free tier", configured: false, badge: "🔑 API" },
];

const CTA_PRESETS = [
  { id: "demo", title: "Попробуй бесплатно", url: "excella.ru" },
  { id: "bot", title: "Гайд в боте", url: "@excella_bot" },
  { id: "directmsg", title: "Пиши слово SUPPORT", url: "в директ" },
  { id: "case", title: "Кейс по ссылке", url: "excella.ru/cases" },
  { id: "none", title: "— без CTA —", url: "" },
];

const RECENT_JOBS = [
  { title: "X10 к сделке: у 25% контактов уже есть нужный ЛПР", count: 5 },
  { title: "Afterresearch ии который улучшает ии", count: 10 },
  { title: "Главный закон переговоров миром правит с…", count: 8 },
  { title: "Русский малый бизнес уже обогнал весь мир — а…", count: 5 },
  { title: "Анти хейт как защитить репутацию", count: 8 },
  { title: "Главная боль предпринимателя я был тупым", count: 8 },
  { title: "Как я выучил английский за год ради выступлени…", count: 5 },
  { title: "Как зарабатывать на syntexai", count: 8 },
  { title: "Почему 500 000 рублей за одну встречу — это вы…", count: 3 },
  { title: "Флажок событие которое перепрошьёт реаль…", count: 15 },
];

const READY_CLIPS = [
  {
    id: 1,
    n: 1,
    title: "X10 к сделке: 25% контактов уже знают вашего ЛПР",
    range: "1:03 – 1:48",
    duration: "45с",
    activeStyle: "bigwhite",
    description:
      "Выход на ЛПР через проводника даёт X10 к скорости сделки. 25% контактов в вашей телефонной книжке уже ведут к нужному человеку. Используйте личную сеть и бизнес-клубы — не обесценивайте свою записную книжку. Подробнее: https://excella.ru",
    hashtags:
      "#B2Bпродажи #ЛПР #холодныепродажи #нетворкинг #b2bsales #salesstrategy #SaaS #проводник #excella #founders #ecommerce",
    poster: "scene-pink",
  },
  {
    id: 2,
    n: 2,
    title: "Проводник к ЛПРу: x10 к скорости сделки",
    range: "5:12 – 5:54",
    duration: "42с",
    activeStyle: "karaoke",
    description:
      "Один знакомый, который знает ЛПР — это в 10 раз быстрее холодного звонка. Используйте бизнес-клубы и личные нетворки. Подробнее: https://excella.ru",
    hashtags: "#нетворкинг #B2B #ЛПР #продажи #excella",
    poster: "scene-emerald",
  },
  {
    id: 3,
    n: 3,
    title: "50 контактов — ноль. Первый контракт пришёл из стопки №51",
    range: "8:30 – 9:18",
    duration: "48с",
    activeStyle: "block",
    description:
      "Воронка холодных продаж — это математика. Не сдавайтесь до 100 контактов. Подробнее: https://excella.ru",
    hashtags: "#холодныепродажи #воронка #B2B #SaaS #excella",
    poster: "scene-amber",
  },
  {
    id: 4,
    n: 4,
    title: "Называй компанию — найдёшь ЛПРа в 10 раз быстрее",
    range: "12:04 – 12:52",
    duration: "48с",
    activeStyle: "neon",
    description:
      "Когда говоришь «ищу директора по маркетингу из Озон» — сеть собирается за час. Подробнее: https://excella.ru",
    hashtags: "#нетворкинг #ЛПР #B2B #excella",
    poster: "scene-violet",
  },
  {
    id: 5,
    n: 5,
    title: "Заплатила 6 млн не за найм — за 10 встреч с CEO",
    range: "18:22 – 19:08",
    duration: "46с",
    activeStyle: "telegram",
    description:
      "Ценность бизнес-клуба — не люди, а доступ. Подробнее: https://excella.ru",
    hashtags: "#бизнесклуб #нетворкинг #B2B #excella",
    poster: "scene-pink",
  },
];

const METRICS_ROWS = [
  { title: "Проводник к ЛПРу: x10 к скорости сделки", brand: "excella" },
  { title: "X10 к сделке: 25% контактов уже знают вашего ЛПР", brand: "excella" },
  { title: "50 контактов — ноль. Первый контракт пришёл из сто…", brand: "excella" },
  { title: "Называй компанию — найдёшь ЛПРа в 10 раз быстрее", brand: "excella" },
  { title: "Миллион за встречу — копейки. Математика B2B", brand: "excella" },
  { title: "Заплатила 6 млн не за найм — за 10 встреч с CEO", brand: "excella" },
];

const PICKER_PROMPT_DEFAULT = `Ты — топовый продюсер вертикальных шортсов на 1М+ просмотров.
Знаешь что такое «wow-моменты» и виральные крючки. Видишь разницу между
«просто интересным фрагментом» и моментом, который остановит scroll.

Из транскрипта длинного видео выбери 5–10 САМЫХ СИЛЬНЫХ фрагментов
25–60 секунд.

Критерии виральности (выбирай ТОЛЬКО те, у которых ВСЕ 4 пункта):
1. Сильный hook в первые 3 секунды: парадокс, вопрос-провокация,
   неожиданный факт, контр-интуитивное утверждение, конкретная цифра/история. НЕ
   «итак, сегодня поговорим».
2. Законченная мысль: фрагмент должен иметь чёткое начало и финал.
3. Эмоциональный пик или конкретный инсайт.
4. Платформенно-независимый: понятен без контекста длинного видео.`;

const META_PROMPT_DEFAULT = `Ты — SEO-специалист по коротким видео для русского рынка.
Для каждого клипа сгенерируй:
1. Заголовок до 60 знаков (с цифрой/триггером где возможно)
2. Описание 2–3 коротких абзаца. Заверши: "Подробнее: {LEAD_URL}"
3. 8–14 хэштегов: 3 высокочастотных, 5–7 нишевых, 2–4 длинных хвоста
   на русском и английском.

Голос бренда: {VOICE}. Ниша: {NICHE}. Аудитория: {AUDIENCE}.`;

window.MOCK = {
  SUBTITLE_STYLES,
  LLM_PROVIDERS,
  CTA_PRESETS,
  RECENT_JOBS,
  READY_CLIPS,
  METRICS_ROWS,
  PICKER_PROMPT_DEFAULT,
  META_PROMPT_DEFAULT,
};
