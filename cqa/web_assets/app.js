"use strict";

const { translate: tr, html: ui, text: msg } = window.CqaI18n;
const { isProblem, problemQueue, reviewStep, externalRecordingUrl } = window.CqaWorkflows;

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (v, digits = 2) =>
  v === null || v === undefined
    ? "—"
    : Number(v).toLocaleString(CqaI18n.locale, {
        maximumFractionDigits: digits,
      });
const date = (v) =>
  v
    ? new Date(v).toLocaleString(
        CqaI18n.language === "kk" ? "ru-RU" : CqaI18n.locale,
        {
          day: "2-digit",
          // Numeric Kazakh months also work in browsers with incomplete CLDR data.
          month: CqaI18n.language === "kk" ? "2-digit" : "short",
          hour: "2-digit",
          minute: "2-digit",
        },
      )
    : "";
const icons = {
  globe:
    "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z M3 12h18 M12 3c5 5 5 13 0 18 M12 3c-5 5-5 13 0 18",
  sun: "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1.5 1.5 M17.5 17.5l1.5 1.5 M5 19l1.5-1.5 M17.5 6.5 19 5",
  moon: "M20.5 14A9 9 0 0 1 10 3.5 9 9 0 1 0 20.5 14Z",
  chat: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5A8.5 8.5 0 0 1 10.5 3h2a8.5 8.5 0 0 1 8.5 8.5Z M7 9h9 M7 13h6",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  chart: "M4 20V11 M10 20V4 M16 20V8 M22 20H2",
  checklist:
    "M8 5h12 M8 12h12 M8 19h12 M2 5l1 1 2-3 M2 12l1 1 2-3 M2 19l1 1 2-3",
  scales: "M12 3v17 M7 21h10 M4 7l8-2 8 2 M4 7 1 14h6L4 7Z M20 7l-3 7h6l-3-7Z",
  search: "m21 21-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
  plus: "M12 5v14 M5 12h14",
  close: "m6 6 12 12 M6 18 18 6",
  arrow: "M5 12h14 M13 6l6 6-6 6",
  upRight: "M6 18 18 6 M6 6h12v12",
  down: "m6 9 6 6 6-6",
  left: "m15 5-7 7 7 7",
  right: "m9 5 7 7-7 7",
  download: "M12 3v12 m-5-5 5 5 5-5 M4 15v6h16v-6",
  upload: "M12 16V3 m-5 5 5-5 5 5 M4 15v6h16v-6",
  alert: "m12 3 10 18H2L12 3Z M12 9v5 M12 17v.5",
  check: "m5 12 4 4 10-10",
  circle: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  shield: "m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Z m-4 10 3 3 5-5",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z M12 7v5l3 2",
  phone: "M7 3H3c-1 10 8 19 18 18v-4l-5-2-2 2a14 14 0 0 1-7-7l2-2-2-5Z",
  play: "m8 4 13 8-13 8V4Z",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  refresh:
    "M3 10a9 9 0 0 1 16-6l2 3 M21 2v5h-5 M21 14a9 9 0 0 1-16 6l-2-3 M3 22v-5h5",
  file: "M14 2H5v20h14V7l-5-5Z M14 2v6h5 M8 12h8 M8 16h5",
  info: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z M12 11v6 M12 7v.5",
  settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  trash: "M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7",
  spark: "m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2Z",
  link: "m10 13 4-4 M8 16l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0 M16 8l1-1a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0",
  sort: "M8 3v18 m-4-4 4 4 4-4 M16 21V3 m-4 4 4-4 4 4",
  back: "M20 12H4 m6-6-6 6 6 6",
  bell: "M5 17V9a7 7 0 0 1 14 0v8l2 2H3l2-2Z M10 22h4",
};
const icon = (name, extra = "") =>
  `<svg class="icon ${extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[name] || icons.circle}"/></svg>`;
const pill = (text, color = "gray", dot = false) =>
  `<span class="pill ${color}">${dot ? '<i class="dot"></i>' : ""}${esc(text)}</span>`;
const S = {
  data: null,
  model: null,
  page: "dialogues",
  q: "",
  language: "all",
  channel: "all",
  filter: "all",
  sort: "id",
  offset: 0,
  selected: new Set(),
  importedIds: new Set(),
  role: (() => {
    try {
      return localStorage.getItem("cqa-role") || "reviewer";
    } catch {
      return "reviewer";
    }
  })(),
  detail: null,
  openCriteria: new Set(),
  showContext: false,
  transcriptSearch: "",
  appealFilter: "pending",
  checklist: null,
  draft: null,
  dirty: false,
  poll: null,
  reviewQueue: loadReviewQueue(),
  inReview: false,
  compare: null,
  reviewComparison: null,
};
let previousFocus;
let routeRequest = 0;

function loadReviewQueue() {
  try {
    const queue = JSON.parse(sessionStorage.getItem("cqa-review-queue"));
    return queue &&
      Array.isArray(queue.ids) &&
      queue.ids.every((id) => typeof id === "string") &&
      queue.context
      ? queue
      : null;
  } catch {
    return null;
  }
}
function saveReviewQueue() {
  try {
    sessionStorage.setItem("cqa-review-queue", JSON.stringify(S.reviewQueue));
  } catch {
    /* In-memory navigation still works. */
  }
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let result;
  try {
    result = await response.json();
  } catch {
    throw new Error(tr("Сервер вернул неожиданный ответ. Обновите страницу."));
  }
  if (!response.ok) {
    let message = result.detail || tr("Не удалось выполнить действие");
    if (Array.isArray(message))
      message = message
        .map((e) => `${e.loc?.slice(1).join(".") || tr("Данные")}: ${e.msg}`)
        .join("; ");
    throw Object.assign(
      new Error(
        typeof message === "string" ? tr(message) : JSON.stringify(message),
      ),
      { status: response.status },
    );
  }
  return result;
}
function toast(message, error = false) {
  const div = document.createElement("div");
  div.className = `toast ${error ? "error" : ""}`;
  div.innerHTML =
    icon(error ? "alert" : "check") + `<span>${esc(message)}</span>`;
  $("#toasts").append(div);
  setTimeout(() => div.remove(), error ? 9000 : 4500);
}
function openModal(title, subtitle, content, footer = "", formId = "") {
  const m = $("#modal");
  if (!m.open) previousFocus = document.activeElement;
  m.classList.remove("comparison-modal");
  S.compare = null;
  S.reviewComparison = null;
  m.innerHTML = ui`${formId ? `<form id="${formId}">` : ""}<div class="modal-head"><div><h2 id="modal-title">${esc(title)}</h2>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div><button type="button" class="icon-btn" data-action="close-modal" aria-label="Закрыть">${icon("close")}</button></div><div class="modal-body">${content}<div id="modal-error" hidden></div></div>${footer ? `<div class="modal-foot">${footer}</div>` : ""}${formId ? "</form>" : ""}`;
  if (!m.open) m.showModal();
}
function closeModal() {
  S.compare = null;
  S.reviewComparison = null;
  $("#modal").close();
  previousFocus?.focus();
}
function modalError(message) {
  const el = $("#modal-error");
  if (el) {
    el.hidden = false;
    el.className = "form-error";
    el.textContent = message;
  } else toast(message, true);
}
const cancelButton = () =>
  ui(
    '<button class="btn outline" type="button" data-action="close-modal">Отмена</button>',
  );
const loading = () =>
  ui(
    '<div class="loading-panel"><span class="spinner"></span><p>Загружаем данные…</p></div>',
  );
const langName = (code) =>
  ({ RU: tr("Русский"), KZ: tr("Казахский"), EN: tr("Английский") })[code] ||
  code;
const originName = (v) =>
  ({
    baseline: tr("Сохранённый результат"),
    model: tr("Анализ модели"),
    recalculated: tr("Пересчёт весов"),
  })[v] || tr("Нет оценки");
const answerName = (a) => ({ yes: tr("Да"), no: tr("Нет"), na: "N/A" })[a] ?? a;
function activeChecklist() {
  const a = S.data.active_checklist;
  return S.data.checklists.find(
    (c) => c.id === a.id && c.version === a.version,
  );
}
function metrics(rows = S.data.conversations) {
  const rated = rows.filter((r) => r.score !== null);
  return {
    total: rows.length,
    rated: rated.length,
    avg: rated.length
      ? rated.reduce((a, r) => a + Number(r.score), 0) / rated.length
      : null,
    critical: rows.filter((r) => r.critical).length,
    pending: S.data.appeals.filter((a) => a.status === "pending").length,
    unrated: rows.filter((r) => r.status === "unrated").length,
  };
}
function shell() {
  $("#app").innerHTML =
    ui`<aside class="sidebar"><a href="#/dialogues" class="brand" aria-label="CQA — диалоги"><img src="/assets/mark.svg" alt=""><div class="brand-copy"><div class="brand-name">CQA<span style="color:#bbace4">.</span></div><div class="brand-sub">QUALITY WORKSPACE</div></div></a><div class="nav-caption">РАБОЧЕЕ ПРОСТРАНСТВО</div><nav aria-label="Основная навигация">${[
      ["dialogues", "chat", tr("Диалоги")],
      ["analytics", "chart", tr("Аналитика")],
      ["appeals", "scales", tr("Апелляции")],
      ["checklists", "checklist", tr("Чек-листы")],
    ]
      .map(
        ([page, i, t]) =>
          `<a class="nav-item" data-nav="${page}" aria-label="${t}" title="${t}" href="#/${page}">${icon(i)}<span class="nav-label">${t}</span><span class="count" id="nav-count-${page}" hidden></span></a>`,
      )
      .join(
        "",
      )}</nav><div class="sidebar-bottom"><div class="side-tip">${icon("shield")}<strong>Решения с основанием</strong>От оценки — к реплике.<br>От вопроса — к решению.</div><div class="side-footer"><i class="dot"></i><span>Локальное пространство</span></div></div></aside>
 <div class="shell"><header class="topbar"><div class="crumb"><span>Контроль качества</span>${icon("right", "small")}<b id="breadcrumb">Диалоги</b></div><div class="top-actions"><div class="display-controls" role="group" aria-label="Настройки отображения"><label class="language-control" for="ui-language">${icon("globe", "small")}<select id="ui-language" aria-label="Язык интерфейса" title="Язык интерфейса"><option value="ru" lang="ru">RU · Русский</option><option value="kk" lang="kk">KZ · Қазақша</option><option value="en" lang="en">EN · English</option></select></label><button class="icon-btn theme-toggle" id="theme-toggle" data-action="toggle-theme" type="button" aria-label="Включить тёмную тему"></button></div><button class="model-chip" id="model-chip" data-action="model-info"><i class="dot"></i><span class="model-name">Проверяем модель…</span></button><button class="icon-btn" data-action="jobs" aria-label="Очередь анализа" title="Очередь анализа">${icon("clock")}<span id="jobs-count" class="count" hidden></span></button><div class="role-control"><span class="avatar" id="role-avatar">QC</span><div><div class="role-caption">Роль в демонстрации</div><select id="role" aria-label="Роль пользователя"><option value="reviewer">Проверяющий</option><option value="operator">Оператор</option></select></div></div></div></header><main id="main" class="main" tabindex="-1"></main></div>`;
  $("#role").value = S.role;
  updatePreferences();
}
function updateChrome() {
  updatePreferences();
  $$("[data-nav]").forEach((a) => {
    const on = a.dataset.nav === S.page;
    a.classList.toggle("active", on);
    on
      ? a.setAttribute("aria-current", "page")
      : a.removeAttribute("aria-current");
  });
  $("#breadcrumb").textContent = {
    dialogues: S.detail ? tr("Анализ разговора") : tr("Диалоги"),
    analytics: tr("Аналитика"),
    appeals: tr("Апелляции"),
    checklists: tr("Чек-листы"),
  }[S.page];
  const pending = S.data.appeals.filter((a) => a.status === "pending").length;
  for (const [key, n] of [
    ["dialogues", S.data.conversations.length],
    ["appeals", pending],
  ]) {
    const e = $("#nav-count-" + key);
    e.textContent = n;
    e.hidden = !n;
  }
  const running = S.data.jobs.filter((j) =>
    ["queued", "running"].includes(j.status),
  ).length;
  $("#jobs-count").textContent = running;
  $("#jobs-count").hidden = !running;
  $("#role-avatar").textContent = S.role === "reviewer" ? "QC" : "OP";
  if (S.model) {
    const e = $("#model-chip");
    e.classList.toggle("ready", S.model.ready);
    e.title = tr(S.model.detail);
    $(".model-name", e).textContent = S.model.ready
      ? S.model.name
      : tr("Модель не подключена");
  }
}
function updatePreferences() {
  const select = $("#ui-language");
  if (select) select.value = CqaI18n.language;
  const button = $("#theme-toggle");
  if (button) {
    const dark = CqaI18n.theme === "dark";
    button.innerHTML = icon(dark ? "sun" : "moon");
    button.title = dark
      ? tr("Включить светлую тему")
      : tr("Включить тёмную тему");
    button.setAttribute("aria-label", button.title);
  }
  $$("[data-i18n]").forEach((el) => {
    el.textContent = tr(el.dataset.i18n);
  });
}
function changeInterfaceLanguage(language) {
  // Re-render labels from the existing state, without reloading the data or
  // replacing a saved evaluation, the user's filters, or their rubric draft.
  const scroll = window.scrollY;
  const transcriptScroll = $("#transcript")?.scrollTop || 0;
  const openRules = $$(".edit-criterion[open]").map((e) => e.dataset.editIndex);
  const highlighted = $$(".message.highlight").map((e) => e.id);
  const audio = $("audio");
  const audioTime = audio?.currentTime || 0;
  CqaI18n.setLanguage(language);
  shell();
  if (S.data) {
    S.detail ? renderDetail() : renderPage();
    openRules.forEach((i) =>
      $(`[data-edit-index="${i}"]`)?.setAttribute("open", ""),
    );
    highlighted.forEach((id) => $("#" + id)?.classList.add("highlight"));
    const transcript = $("#transcript");
    if (transcript) transcript.scrollTop = transcriptScroll;
    const replacementAudio = $("audio");
    if (replacementAudio && audioTime) {
      replacementAudio.addEventListener(
        "loadedmetadata",
        () => {
          replacementAudio.currentTime = audioTime;
        },
        { once: true },
      );
    }
    updateChrome();
  } else $("#main").innerHTML = loading();
  document.title =
    (S.detail
      ? tr("Разбор ") + S.detail.dialogue.conversation_id
      : $("#breadcrumb").textContent) + " · CQA";
  window.scrollTo({ top: scroll, behavior: "instant" });
  $("#ui-language")?.focus({ preventScroll: true });
}
async function refreshData() {
  S.data = await api("/ui-api/bootstrap");
  updateChrome();
}
async function route() {
  const request = ++routeRequest;
  const [path, query = ""] = (location.hash.slice(1) || "/dialogues").split(
    "?",
  );
  S.page = ["/analytics", "/appeals", "/checklists"].includes(path)
    ? path.slice(1)
    : "dialogues";
  S.detail = null;
  updateChrome();
  const params = new URLSearchParams(query);
  const id = params.get("id");
  S.inReview =
    params.get("review") === "1" && Boolean(S.reviewQueue?.ids.includes(id));
  if (S.page === "dialogues" && id) {
    $("#main").innerHTML = loading();
    try {
      const evaluation = params.get("evaluation_id");
      const detail = await api(
        "/ui-api/conversations/" +
          encodeURIComponent(id) +
          (evaluation
            ? "?evaluation_id=" + encodeURIComponent(evaluation)
            : ""),
      );
      if (request !== routeRequest) return;
      S.detail = detail;
      S.openCriteria = new Set([
        S.detail.result?.scoring?.violation_criteria?.[0] ||
          S.detail.result?.checklist.criteria.find((c) => c.id === "c4")?.id ||
          S.detail.result?.checklist.criteria[0]?.id,
      ]);
      renderDetail();
    } catch (e) {
      if (request !== routeRequest) return;
      $("#main").innerHTML = empty(
        tr("Диалог не найден"),
        e.message,
        "chat",
        tr("К списку"),
        "go-dialogues",
      );
    }
  } else renderPage();
  updateChrome();
  document.title =
    (id
      ? tr("Разбор ") + id
      : {
          dialogues: tr("Диалоги"),
          analytics: tr("Аналитика"),
          appeals: tr("Апелляции"),
          checklists: tr("Чек-листы"),
        }[S.page]) + " · CQA";
  window.scrollTo({ top: 0, behavior: "instant" });
  const turn = Number(params.get("turn"));
  if (
    S.detail &&
    Number.isInteger(turn) &&
    turn > 0 &&
    turn <= S.detail.dialogue.transcript.length
  )
    jumpEvidence(turn);
}
function renderPage() {
  if (S.page === "dialogues") renderDialogues();
  else if (S.page === "appeals") renderAppeals();
  else if (S.page === "checklists") renderChecklists();
  else renderAnalytics();
  updateChrome();
}
function queueContext() {
  return {
    q: S.q,
    language: S.language,
    channel: S.channel,
    filter: S.filter,
    importedIds: S.filter === "file" ? [...S.importedIds] : [],
    sort: S.sort,
    offset: S.offset,
  };
}
function conversationHref(id, evaluation = null, review = false, turn = null) {
  const query = new URLSearchParams({ id });
  if (evaluation) query.set("evaluation_id", evaluation);
  if (review) query.set("review", "1");
  if (turn) query.set("turn", String(turn));
  return "#/dialogues?" + query;
}
function reviewHref(id) {
  const row = S.data.conversations.find((r) => r.id === id);
  return conversationHref(id, row?.review_evaluation_id, true);
}
async function startReview(fromDetail = false) {
  await refreshData();
  const current = fromDetail ? S.detail?.dialogue.conversation_id : null;
  const ids = problemQueue(filtered(), current);
  if (!ids.length) {
    toast(tr("В текущей подборке нет проблемных диалогов"));
    return;
  }
  S.reviewQueue = { ids, context: queueContext() };
  saveReviewQueue();
  const target =
    current && ids[0] === current
      ? reviewStep(ids, current, S.data.conversations)
      : ids[0];
  if (!target) {
    toast(tr("Других проблемных диалогов в подборке нет"));
    return;
  }
  location.hash = reviewHref(target);
}
async function moveReview(direction) {
  await refreshData();
  const id = reviewStep(
    S.reviewQueue?.ids || [],
    S.detail.dialogue.conversation_id,
    S.data.conversations,
    direction,
  );
  if (id) location.hash = reviewHref(id);
  else {
    renderReviewNavigation();
    toast(tr("Дальше нет проблемных диалогов в этой подборке"));
  }
}
function leaveReview() {
  if (S.reviewQueue?.context) {
    const { q, language, channel, filter, sort, offset, importedIds } =
      S.reviewQueue.context;
    Object.assign(S, { q, language, channel, filter, sort, offset });
    if (filter === "file") S.importedIds = new Set(importedIds);
  }
  S.inReview = false;
  S.reviewQueue = null;
  saveReviewQueue();
  location.hash = "/dialogues";
}
function renderReviewNavigation() {
  const host = $("#review-navigation");
  if (!host || !S.detail) return;
  const id = S.detail.dialogue.conversation_id;
  if (!S.inReview || !S.reviewQueue) {
    const count = filtered().filter((r) => isProblem(r) && r.id !== id).length;
    host.innerHTML = ui`<div class="review-navigation"><div>${icon("eye")}<span>Проверка проблемных диалогов</span></div><button class="btn outline sm" data-action="start-review-detail" ${count ? "" : "disabled"}>Следующий проблемный диалог ${icon("arrow", "small")}</button></div>`;
    return;
  }
  const ids = S.reviewQueue.ids;
  const next = reviewStep(ids, id, S.data.conversations);
  const previous = reviewStep(ids, id, S.data.conversations, -1);
  host.innerHTML = ui`<div class="review-navigation active"><div class="review-navigation-copy"><strong>Подборка для проверки</strong><span>${ids.indexOf(id) + 1} из ${ids.length} · порядок зафиксирован при открытии</span><small>${next ? tr("Следующий переход пропускает диалоги без актуальных проблем.") : tr("Дальше нет проблемных диалогов в этой подборке")}</small></div><div class="actions"><button class="text-btn" data-action="leave-review">К списку подборки</button><button class="icon-btn" data-action="review-previous" aria-label="Предыдущий диалог подборки" title="Предыдущий диалог подборки" ${previous ? "" : "disabled"}>${icon("left")}</button><button class="btn primary sm" data-action="review-next" ${next ? "" : "disabled"}>Следующий проблемный ${icon("arrow", "small")}</button></div></div>`;
}
function updateReviewEntry() {
  const button = $("#start-review");
  if (!button) return;
  const count = filtered().filter(isProblem).length;
  button.disabled = !count;
  button.innerHTML =
    icon("eye", "small") + " " + esc(msg`Проверить проблемные · ${count}`);
}
function comparisonFieldLabel(field) {
  return (
    {
      title: tr("Название"),
      notes: tr("Общие инструкции"),
      total_max: tr("Максимум итоговой оценки"),
      order: tr("Порядок критериев"),
      section: tr("Раздел"),
      kind: tr("Тип ответа"),
      weight: tr("Вес"),
      max_score: tr("Максимум шкалы"),
      rule: tr("Правило"),
      options: tr("Варианты ответа и баллы"),
      na_conditions: tr("Условия N/A"),
      channel_rules: tr("Правила для каналов"),
      requires_company_knowledge: tr("Нужны знания компании"),
      max_observed_facts: tr("Максимум наблюдаемых фактов"),
      violation_value: tr("Ответ, означающий грубую ошибку"),
      flag_evidence_mode: tr("Требование к доказательству грубой ошибки"),
    }[field] || field
  );
}
function comparisonValue(field, value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    (Array.isArray(value) && !value.length) ||
    (typeof value === "object" && !Object.keys(value).length)
  )
    return `<span class="muted">${esc(tr("Не задано"))}</span>`;
  if (typeof value === "boolean") return esc(answerName(value ? "yes" : "no"));
  if (["weight", "total_max", "max_score"].includes(field))
    return esc(num(value));
  if (field === "kind")
    return esc(
      { binary: tr("Да / Нет"), scale: tr("Шкала"), flag: tr("Грубая ошибка") }[
        value
      ] || value,
    );
  if (field === "violation_value") return esc(answerName(value));
  if (field === "flag_evidence_mode" && value === "operator_action")
    return esc(tr("Доказательство действия оператора"));
  if (field === "order")
    return esc(value.map((id) => id.toUpperCase()).join(" → "));
  if (field === "options")
    return `<ul>${value.map((o) => `<li><strong>${esc(answerName(o.value))} · ${num(o.raw_score)}</strong><br>${esc(o.description)}</li>`).join("")}</ul>`;
  if (field === "na_conditions")
    return `<ul>${value.map((n) => `<li><strong>${esc(n.id)}</strong> · ${esc(n.description)}${n.channels ? `<br><small>${esc(n.channels.map((c) => (c === "voice call" ? tr("Звонки") : tr("Чаты"))).join(", "))}</small>` : ""}</li>`).join("")}</ul>`;
  if (field === "channel_rules")
    return `<ul>${Object.entries(value)
      .map(
        ([key, text]) =>
          `<li><strong>${esc(key === "voice call" ? tr("Звонки") : key === "agent chat" ? tr("Чаты") : key)}</strong><br>${esc(text)}</li>`,
      )
      .join("")}</ul>`;
  return esc(value);
}
function fieldDifference(field, before, after) {
  return ui`<div class="field-difference"><h4>${esc(comparisonFieldLabel(field))}</h4><div class="compare-columns"><div class="diff-before"><small>Было</small><div>${comparisonValue(field, before)}</div></div><div class="diff-after"><small>Стало</small><div>${comparisonValue(field, after)}</div></div></div></div>`;
}
function openChecklistComparison() {
  const base = S.checklist || activeChecklist();
  const lists = S.data.checklists;
  const selected = lists.findIndex(
    (c) => c.id === base.id && c.version === base.version,
  );
  const previous = lists
    .map((c, i) => (c.id === base.id && i < selected ? i : -1))
    .filter((i) => i >= 0)
    .at(-1);
  const before = S.dirty ? selected : (previous ?? selected);
  const after = S.dirty ? "draft" : String(selected);
  const options = lists
    .map(
      (c, i) =>
        `<option value="${i}">v${esc(c.version)} · ${esc(c.title)} · ${esc(c.id)}</option>`,
    )
    .join("");
  openModal(
    tr("Сравнение версий чек-листа"),
    tr("Точные изменения правил, шкал и весов"),
    ui`<div class="comparison-controls"><div><label for="compare-before">Исходная версия</label><select id="compare-before">${options}</select></div><span class="comparison-direction">${icon("arrow")}</span><div><label for="compare-after">Сравнить с</label><select id="compare-after">${options}${S.dirty ? ui`<option value="draft">Несохранённый черновик · v${esc(S.draft.version)}</option>` : ""}</select></div></div><label class="toggle-label comparison-toggle"><input type="checkbox" id="compare-unchanged"> Показывать совпадающие критерии</label><div id="checklist-comparison-body" aria-live="polite"></div>`,
    ui`<p class="foot-note">Сравнение не меняет действующую версию и не запускает модель.</p><button class="btn primary" data-action="close-modal" type="button">Готово</button>`,
  );
  $("#modal").classList.add("comparison-modal");
  $("#compare-before").value = String(before);
  $("#compare-after").value = after;
  S.compare = {
    before: String(before),
    after,
    showUnchanged: false,
    draft: S.dirty ? structuredClone(S.draft) : null,
    request: 0,
  };
  refreshChecklistComparison();
}
async function refreshChecklistComparison() {
  const state = S.compare;
  if (!state) return;
  const request = ++state.request;
  state.result = null;
  $("#checklist-comparison-body").innerHTML = loading();
  const ref = (index) => {
    const c = S.data.checklists[Number(index)];
    return { id: c.id, version: c.version };
  };
  try {
    const payload = {
      before: ref(state.before),
      ...(state.after === "draft"
        ? { draft: state.draft }
        : { after: ref(state.after) }),
    };
    const result = await api("/ui-api/checklists/compare", "POST", payload);
    if (S.compare !== state || state.request !== request) return;
    state.result = result;
    renderChecklistComparison();
  } catch (error) {
    if (S.compare !== state || state.request !== request) return;
    $("#checklist-comparison-body").innerHTML =
      state.after === "draft" && error.status === 422
        ? ui`<div class="form-error"><p>Для сравнения черновика заполните обязательные поля и проверьте шкалы.</p><button type="button" class="btn outline sm" data-action="validate-draft">Вернуться к черновику</button></div>`
        : `<div class="form-error">${esc(error.message)}</div>`;
  }
}
function renderChecklistComparison() {
  const state = S.compare,
    result = state?.result;
  if (!result) return;
  const rows = result.criteria.filter(
    (row) => state.showUnchanged || row.status !== "unchanged",
  );
  const headline =
    result.mode === "reanalyze"
      ? tr("Нужен новый анализ")
      : result.mode === "recalculate"
        ? tr("Достаточно пересчитать баллы")
        : tr("Ответы совместимы");
  const help =
    result.mode === "reanalyze"
      ? tr(
          "Изменились условия оценки. Ответы старой версии нельзя автоматически перенести на новые правила.",
        )
      : result.mode === "recalculate"
        ? tr(
            "Условия ответов совпадают. Новый итог можно получить из исходных ответов без вызова модели.",
          )
        : tr(
            "Условия ответов и формула совпадают. Отличие номера версии само по себе не требует вызова модели.",
          );
  const globals =
    result.global_fields
      .map((key) => fieldDifference(key, result.before[key], result.after[key]))
      .join("") +
    (result.reordered
      ? fieldDifference(
          "order",
          result.before.criteria.map((c) => c.id),
          result.after.criteria.map((c) => c.id),
        )
      : "");
  const statusNames = {
    added: tr("Добавлен"),
    removed: tr("Удалён"),
    changed: tr("Изменён"),
    unchanged: tr("Без изменений"),
  };
  $("#checklist-comparison-body").innerHTML =
    ui`<div class="notice ${result.mode === "reanalyze" ? "amber" : ""}">${icon(result.mode === "reanalyze" ? "alert" : "check")}<div><strong>${esc(headline)}</strong><p>${esc(help)}</p></div></div><div class="comparison-counts"><span>Изменено <b>${result.counts.changed}</b></span><span>Добавлено <b>${result.counts.added}</b></span><span>Удалено <b>${result.counts.removed}</b></span><span>Совпадает <b>${result.counts.unchanged}</b></span></div><details class="comparison-impact"><summary>Что потребуется для диалогов в рабочем пространстве</summary><p class="form-help">Расчёт для выбранной целевой версии по последней оценке каждого диалога.</p><div class="impact-grid"><div><b>${result.impact.current}</b><span>Уже на целевой версии</span></div><div><b>${result.impact.recalculate}</b><span>Пересчёт без модели</span></div><div><b>${result.impact.reanalyze}</b><span>Новый анализ</span></div><div><b>${result.impact.unrated + result.impact.failed}</b><span>Без завершённой оценки</span></div></div></details>${globals ? ui`<section class="comparison-row"><h3>Общие изменения</h3>${globals}</section>` : ""}${rows
      .map((row) => {
        const c = row.after || row.before;
        const fields =
          row.status === "added" || row.status === "removed"
            ? [
                "kind",
                "weight",
                "max_score",
                "rule",
                "options",
                "na_conditions",
                "channel_rules",
                "requires_company_knowledge",
                "max_observed_facts",
                "violation_value",
                "flag_evidence_mode",
              ].filter(
                (key) =>
                  c[key] !== undefined &&
                  c[key] !== null &&
                  (!Array.isArray(c[key]) || c[key].length),
              )
            : row.fields;
        return `<section class="comparison-row"><div class="comparison-row-head"><h3><span class="criterion-index">${esc(row.id.toUpperCase())}</span> ${esc(c.title)}</h3>${pill(statusNames[row.status], row.status === "added" ? "green" : row.status === "removed" ? "red" : row.status === "changed" ? "purple" : "gray")}</div>${fields.map((key) => fieldDifference(key, row.before?.[key], row.after?.[key])).join("")}</section>`;
      })
      .join(
        "",
      )}${!rows.length && !globals ? ui`<div class="comparison-empty">${icon("check")} Условия оценки совпадают</div>` : ""}`;
}
async function openReviewComparison(evaluationId, appealId = null) {
  openModal(
    tr("До / после апелляции"),
    tr("Изменения ответов, баллов и оснований"),
    ui`<div class="field"><label for="review-comparison-scope">Что сравнить</label><select id="review-comparison-scope" disabled><option>Загружаем данные…</option></select></div><label class="toggle-label comparison-toggle"><input type="checkbox" id="review-comparison-unchanged"> Показывать совпадающие критерии</label><div id="review-comparison-body" aria-live="polite"></div>`,
    ui`<button class="btn primary" data-action="close-modal" type="button">Готово</button>`,
  );
  $("#modal").classList.add("comparison-modal");
  S.reviewComparison = {
    evaluationId,
    appealId,
    showUnchanged: false,
    request: 0,
  };
  await refreshReviewComparison();
}
async function refreshReviewComparison() {
  const state = S.reviewComparison;
  if (!state) return;
  const request = ++state.request;
  state.result = null;
  $("#review-comparison-body").innerHTML = loading();
  try {
    const result = await api(
      `/ui-api/evaluations/${encodeURIComponent(state.evaluationId)}/review-comparison${state.appealId ? "?appeal_id=" + encodeURIComponent(state.appealId) : ""}`,
    );
    if (S.reviewComparison !== state || state.request !== request) return;
    state.result = result;
    const select = $("#review-comparison-scope");
    select.innerHTML = ui`<option value="">Исходная оценка → все сохранённые решения</option>${result.appeals.map((a) => `<option value="${esc(a.id)}">${esc(a.criterion_id.toUpperCase())} · ${esc(date(a.resolved_at || a.created_at))} · ${esc(a.status === "resolved" ? tr("Решение сохранено") : tr("На проверке"))}</option>`).join("")}`;
    select.value = state.appealId || "";
    select.disabled = false;
    renderReviewComparison();
  } catch (error) {
    if (S.reviewComparison !== state || state.request !== request) return;
    $("#review-comparison-body").innerHTML =
      `<div class="form-error">${esc(error.message)}</div>`;
  }
}
function deltaText(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return (n > 0 ? "+" : n < 0 ? "−" : "") + num(Math.abs(n));
}
function comparisonScore(title, score) {
  return ui`<section class="comparison-score"><span>${esc(title)}</span><strong class="mono">${score ? num(score.total_score) : "—"}<small>${score ? "/ " + num(score.total_max) : ""}</small></strong>${score ? pill(score.gross_violation ? tr("Грубая ошибка") : tr("Без грубых ошибок"), score.gross_violation ? "red" : "green") : pill(tr("Решение ещё не принято"), "amber")}</section>`;
}
function reviewDecisionSide(decision, title, kind) {
  if (!decision)
    return ui`<div class="review-decision"><small>${esc(title)}</small><p class="muted">Решение ещё не принято</p></div>`;
  return ui`<div class="review-decision"><small>${esc(title)}</small><div class="review-decision-value">${pill(kind === "scale" && decision.answer !== "na" ? answerName(decision.answer) + " / " + num(decision.max_score) : answerName(decision.answer), "gray")}<strong>${kind === "flag" ? tr("Без баллов") : decision.answer === "na" ? "—" : msg`${num(decision.points)} балла`}</strong></div>${kind === "flag" ? ui`<p class="form-help">Отдельный флаг</p>` : ui`<p class="form-help">Вес после N/A: ${num(decision.effective_weight)}</p>`}${decision.na_condition_id ? ui`<p class="form-help">Условие N/A: ${esc(decision.na_condition || decision.na_condition_id)}</p>` : ""}</div>`;
}
function reviewEvidence(decision, result) {
  return (decision?.evidence_turns || [])
    .slice(0, 8)
    .map(
      (turn) =>
        ui`<button class="evidence-btn" data-action="comparison-evidence" data-evaluation="${esc(result.evaluation_id)}" data-conversation="${esc(result.conversation_id)}" data-turn="${turn}">${icon("link")} Реплика ${turn}</button>`,
    )
    .join("");
}
function renderReviewComparison() {
  const state = S.reviewComparison,
    result = state?.result;
  if (!result) return;
  const leftTitle = result.appeal ? tr("До решения") : tr("Исходная оценка");
  const rightTitle = result.appeal
    ? tr("После решения")
    : tr("После всех решений");
  const rows = result.criteria.filter(
    (row) => state.showUnchanged || row.changed || !result.after,
  );
  $("#review-comparison-body").innerHTML =
    ui`<div class="comparison-context"><span>${esc(result.conversation_id)}</span><span>Чек-лист v${esc(result.checklist.version)}</span></div><div class="compare-columns score-comparison">${comparisonScore(leftTitle, result.before)}${comparisonScore(rightTitle, result.after)}</div>${result.after ? ui`<div class="comparison-delta"><span>Изменение итога</span><strong>${deltaText(result.score_delta)}</strong>${result.critical_changed ? pill(tr("Изменён флаг грубой ошибки"), "purple") : ""}</div>` : ui`<div class="notice amber">${icon("clock")}<p>Сохранённого решения пока нет. После рассмотрения здесь появятся изменения.</p></div>`}${result.pending_count ? ui`<p class="form-help comparison-note">Открытых апелляций: ${result.pending_count}. Они ещё не изменяют оценку.</p>` : ""}${result.basis === "reconstructed" ? ui`<p class="form-help comparison-note">Сравнение восстановлено из сохранённой истории решений.</p>` : ""}${result.appeal ? ui`<div class="comparison-appeal"><h3>Аргумент апелляции</h3><p>${esc(result.appeal.comment)}</p><small>${esc(result.appeal.actor)} · ${esc(date(result.appeal.created_at))}</small>${result.appeal.status === "resolved" ? ui`<h3>Решение проверяющего</h3><p>${esc(result.appeal.resolution)}</p><small>${esc(result.appeal.reviewer)} · ${esc(date(result.appeal.resolved_at))}</small>` : ""}</div>` : ""}<p class="form-help comparison-note">N/A может изменить вес и вклад остальных критериев. Грубая ошибка учитывается отдельным флагом.</p>${rows.map((row) => ui`<article class="comparison-row"><div class="comparison-row-head"><h3><span class="criterion-index">${esc(row.id.toUpperCase())}</span> ${esc(tr(row.title))}</h3>${row.answer_changed ? pill(tr("Изменён ответ"), "purple") : row.weight_changed || row.points_changed ? pill(tr("Перераспределён вес"), "amber") : row.reason_changed ? pill(tr("Уточнено основание"), "gray") : ""}</div><div class="compare-columns">${reviewDecisionSide(row.before, leftTitle, row.kind)}${reviewDecisionSide(row.after, rightTitle, row.kind)}</div>${row.points_changed && row.points_delta !== null ? ui`<p class="comparison-row-delta">Изменение вклада: <strong>${deltaText(row.points_delta)}</strong></p>` : ""}<details class="comparison-reasons"><summary>Основания и исходные реплики</summary><div class="compare-columns"><div><small>${esc(leftTitle)}</small><p>${esc(row.before.reason)}</p><div class="evidence-list">${reviewEvidence(row.before, result)}</div></div><div><small>${esc(rightTitle)}</small><p>${esc(row.after?.reason || tr("Решение ещё не принято"))}</p>${row.after ? ui`<p class="form-help">Ссылки относятся к репликам исходной оценки.</p><div class="evidence-list">${reviewEvidence(row.after, result)}</div>` : ""}</div></div></details></article>`).join("")}${!rows.length && result.after ? ui`<div class="comparison-empty">${icon("check")} Ответы, баллы и основания не изменились</div>` : ""}`;
}

function empty(title, text, i = "chat", button = "", action = "") {
  return `<div class="empty"><div class="empty-icon">${icon(i)}</div><h2>${esc(title)}</h2><p>${esc(text)}</p>${button ? `<button class="btn primary" data-action="${action}">${esc(button)} ${icon("arrow", "small")}</button>` : ""}</div>`;
}
function footer() {
  return ui`<div class="footer-note"><span>CQA · Проверяемые оценки, понятные решения</span><span>RU / KZ / EN <span style="padding:0 9px">·</span> Сохранение в локальной базе</span></div>`;
}
function statCards() {
  const m = metrics();
  return ui`<div class="stats"><div class="stat feature"><div class="stat-top">Средняя оценка ${icon("chart")}</div><div class="stat-value mono">${num(m.avg, 1)} <span>/ 100</span></div><div class="stat-bottom">${icon("check", "small")} По ${m.rated} оценённым диалогам</div></div>
 <button class="stat clickable red-number" data-action="filter-critical"><div class="stat-top">Грубые ошибки</div><div class="stat-icon">${icon("upRight")}</div><div class="stat-value mono">${m.critical.toString().padStart(2, "0")}</div><div class="stat-bottom"><i class="dot" style="color:#c37a7e"></i> ${m.critical ? tr("Требуют внимания") : tr("Нарушений не отмечено")}</div></button>
 <button class="stat clickable lilac" data-action="go-appeals"><div class="stat-top">Открытые апелляции</div><div class="stat-icon">${icon("upRight")}</div><div class="stat-value mono">${m.pending.toString().padStart(2, "0")}</div><div class="stat-bottom">${icon("scales", "small")} ${m.pending ? tr("Ожидают вашего решения") : tr("Все решения на одном экране")}</div></button>
 <div class="stat coverage-stat"><div class="stat-top">Оценено диалогов ${icon("checklist")}</div><div class="stat-value mono">${m.rated} <span>/ ${m.total}</span></div><div class="stat-bottom">${m.total && m.rated === m.total ? pill(tr("Все обработаны"), "green", true) : msg`${m.total - m.rated} без завершённой оценки`}</div></div></div>`;
}
function renderDialogues() {
  const m = metrics();
  $("#main").innerHTML =
    ui`<div class="page-head"><div><div class="eyebrow">КАЧЕСТВО В КАЖДОМ РАЗГОВОРЕ</div><h1>Диалоги</h1><p>Находите важное. Проверяйте оценки. Принимайте решения.</p></div><div class="actions"><button class="btn outline" data-action="export">${icon("download", "small")} Экспорт</button><button class="btn primary" data-action="import">${icon("plus", "small")} Загрузить диалоги</button></div></div>${statCards()}
 <section class="card data-card" aria-label="Список диалогов"><div class="data-head"><div class="data-title"><h2>Все разговоры</h2><span class="count">${m.total}</span></div><div class="tabs" aria-label="Фильтр результатов">${[
   ["all", tr("Все")],
   ["critical", tr("Грубые ошибки")],
   ["attention", tr("На проверку")],
   ["unrated", tr("Без оценки")],
   ...(S.importedIds.size ? [["file", tr("Из файла")]] : []),
 ]
   .map(
     ([f, t]) =>
       `<button class="tab ${S.filter === f ? "active" : ""}" data-action="filter" data-value="${f}" aria-pressed="${S.filter === f}">${t}${f === "unrated" && m.unrated ? `<span class="count">${m.unrated}</span>` : ""}</button>`,
   )
   .join("")}</div></div>
 <div class="filters"><div class="search">${icon("search")}<input id="dialogue-search" placeholder="Найти по ID или содержанию запроса…" value="${esc(S.q)}" aria-label="Поиск диалогов"><kbd>⌘ K</kbd></div><select id="language-filter" class="filter-select" aria-label="Язык диалога"><option value="all">Все языки</option>${["RU", "KZ", "EN"].map((l) => `<option value="${l}" ${S.language === l ? "selected" : ""}>${langName(l)}</option>`).join("")}</select><select id="channel-filter" class="filter-select" aria-label="Канал разговора"><option value="all">Все каналы</option><option value="agent chat" ${S.channel === "agent chat" ? "selected" : ""}>Чаты</option><option value="voice call" ${S.channel === "voice call" ? "selected" : ""}>Звонки</option></select><button class="icon-btn" data-action="reset-filters" aria-label="Сбросить фильтры" title="Сбросить фильтры">${icon("refresh", "small")}</button></div><div class="review-list-entry"><span>Проверка с учётом текущих фильтров</span><button type="button" class="btn green sm" data-action="start-review" id="start-review">Проверить проблемные</button></div><div id="dialogue-table"></div></section>${footer()}`;
  renderTable();
}
function filtered() {
  let rows = S.data.conversations.filter(
    (r) =>
      (!S.q ||
        `${r.id} ${r.preview}`.toLowerCase().includes(S.q.toLowerCase())) &&
      (S.language === "all" || r.language === S.language) &&
      (S.channel === "all" || r.channel === S.channel),
  );
  if (S.filter === "attention") rows = rows.filter(isProblem);
  if (S.filter === "critical") rows = rows.filter((r) => r.critical);
  if (S.filter === "unrated") rows = rows.filter((r) => r.status === "unrated");
  if (S.filter === "file") rows = rows.filter((r) => S.importedIds.has(r.id));
  return rows.sort(
    S.sort === "score"
      ? (a, b) =>
          (a.score === null ? 999 : Number(a.score)) -
          (b.score === null ? 999 : Number(b.score))
      : (a, b) => a.id.localeCompare(b.id),
  );
}
function renderTable() {
  const rows = filtered(),
    pages = Math.max(1, Math.ceil(rows.length / 12));
  S.offset = Math.min(S.offset, pages - 1);
  const visible = rows.slice(S.offset * 12, S.offset * 12 + 12);
  const selection = S.selected.size
    ? ui`<div class="selection-bar"><span>Выбрано: <strong>${S.selected.size}</strong></span><div class="actions"><button class="text-btn" data-action="clear-selection">Снять выбор</button><button class="btn green sm" data-action="run-selected">${icon("play", "small")} Оценить выбранные</button></div></div>`
    : "";
  $("#dialogue-table").innerHTML =
    selection +
    (rows.length
      ? ui`<div class="table-wrap"><table><thead><tr><th><input type="checkbox" id="select-page" aria-label="Выбрать диалоги на странице" ${visible.every((r) => S.selected.has(r.id)) ? "checked" : ""}></th><th>Разговор</th><th>Язык</th><th><button class="sort-button" data-action="sort-score">Оценка ${icon("sort")}</button></th><th>Результат</th><th>Версия</th><th></th></tr></thead><tbody>${visible.map((r) => ui`<tr><td><input type="checkbox" data-select="${esc(r.id)}" aria-label="Выбрать ${esc(r.id)}" ${S.selected.has(r.id) ? "checked" : ""}></td><td><div class="conversation-cell"><span class="channel-icon ${r.channel === "voice call" ? "voice" : ""}">${icon(r.channel === "voice call" ? "phone" : "chat")}</span><div><a href="#/dialogues?id=${encodeURIComponent(r.id)}">${esc(r.id)}</a><p class="preview" title="${esc(r.preview)}">${esc(r.preview)}</p></div></div></td><td><span class="language"><b>${r.language}</b><span class="language-word">${langName(r.language)}</span></span></td><td>${r.score !== null ? `<div class="score-cell ${Number(r.score) < 60 ? "low" : ""}"><strong class="mono">${num(r.score, 1)}</strong><span class="score-track"><i style="width:${Math.max(0, Math.min(100, Number(r.score)))}%"></i></span></div>` : '<span class="muted">—</span>'}</td><td>${r.critical ? pill(tr("Грубая ошибка"), "red", true) : r.status === "unrated" ? pill(tr("Без оценки")) : r.status === "failed" ? pill(tr("Ошибка анализа"), "amber", true) : r.needs_review ? pill(tr("Нужна проверка"), "amber", true) : pill(tr("Без грубых ошибок"), "green", true)}${r.pending_appeals ? ui`<div class="origin-text">Апелляция на проверке</div>` : r.reviewed ? ui('<div class="origin-text">Есть решение по апелляции</div>') : ""}</td><td><span class="small muted">${r.version ? "v" + esc(r.version) : "—"}</span><div class="origin-text">${r.origin === "baseline" ? tr("Сохранённая") : r.origin === "recalculated" ? tr("Пересчёт") : r.origin === "model" ? tr("Модель") : ""}</div></td><td><a class="icon-btn" href="#/dialogues?id=${encodeURIComponent(r.id)}" aria-label="Открыть ${esc(r.id)}">${icon("upRight", "small")}</a></td></tr>`).join("")}</tbody></table></div><div class="table-footer"><span>${S.offset * 12 + 1}–${Math.min((S.offset + 1) * 12, rows.length)} из ${rows.length} диалогов${S.filter === "critical" ? tr(" · Только грубые ошибки") : ""}</span><div class="pagination"><button data-action="page" data-value="${S.offset - 1}" ${!S.offset ? "disabled" : ""} aria-label="Предыдущая страница">${icon("left", "small")}</button>${Array.from({ length: pages }, (_, i) => ui`<button data-action="page" data-value="${i}" class="${S.offset === i ? "current" : ""}" aria-label="Страница ${i + 1}" ${S.offset === i ? 'aria-current="page"' : ""}>${i + 1}</button>`).join("")}<button data-action="page" data-value="${S.offset + 1}" ${S.offset >= pages - 1 ? "disabled" : ""} aria-label="Следующая страница">${icon("right", "small")}</button></div></div>`
      : empty(
          S.data.conversations.length
            ? tr("Ничего не найдено")
            : tr("Начните с первого диалога"),
          S.data.conversations.length
            ? tr("Попробуйте другой запрос или сбросьте фильтры.")
            : tr(
                "Загрузите JSON организаторов. Разговоры появятся здесь вместе с языком, каналом и результатами.",
              ),
          "chat",
          S.data.conversations.length
            ? tr("Сбросить фильтры")
            : tr("Загрузить JSON"),
          S.data.conversations.length ? "reset-filters" : "import",
        ));
  updateReviewEntry();
}
function duration(d) {
  try {
    const first = d.transcript[0].timestamp,
      last = d.transcript.at(-1).timestamp;
    let seconds;
    if (d.channel === "voice call")
      seconds = (Date.parse(last) - Date.parse(first)) / 1000;
    else {
      const t = (s) => s.split(":").reduce((a, v) => a * 60 + Number(v), 0);
      seconds = t(last) - t(first);
    }
    return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
  } catch {
    return "—";
  }
}
function timestamp(m, d) {
  if (d.channel !== "voice call") return m.timestamp;
  const diff =
    (Date.parse(m.timestamp) - Date.parse(d.transcript[0].timestamp)) / 1000;
  return `${Math.floor(diff / 60)}:${String(Math.floor(diff % 60)).padStart(2, "0")}`;
}
function onlyWeightsChanged(a, b) {
  const compatibility = S.detail?.compatibility;
  return Boolean(
    compatibility?.can_reweight &&
      compatibility.target.id === b.id &&
      compatibility.target.version === b.version,
  );
}
function renderDetail() {
  const { dialogue: d, result: r, history } = S.detail;
  const externalAudio = S.detail.audio ? null : externalRecordingUrl(d.audio_url);
  const active = activeChecklist();
  const stale =
    r &&
    (r.checklist.id !== active.id || r.checklist.version !== active.version);
  const job = S.data.jobs.find(
    (j) =>
      j.conversation_id === d.conversation_id &&
      ["queued", "running"].includes(j.status),
  );
  $("#main").innerHTML =
    ui`<div class="page-head"><div><a href="#/dialogues" ${S.inReview ? 'data-action="leave-review"' : ""} class="back-link">${icon("back", "small")} Все диалоги</a><h1 class="detail-title">Анализ разговора</h1><div class="detail-meta"><span class="section-meta">${esc(d.conversation_id)}</span>${pill(langName(d.language))}${pill(d.channel === "voice call" ? tr("Звонок") : tr("Чат"))}${pill(d.transcript.length + tr(" реплик"))}${r?.scoring?.gross_violation ? pill(tr("Грубая ошибка"), "red", true) : ""}</div></div><div class="actions"><button class="btn outline" data-action="detail-export">${icon("download", "small")} Отчёт</button><button class="btn primary" data-action="run-detail" ${job ? "disabled" : ""}>${icon(job ? "clock" : "play", "small")}${job ? tr("Анализ выполняется") : r ? tr("Оценить заново") : tr("Оценить диалог")}</button></div></div>
 <div id="review-navigation"></div>
 ${job ? ui`<div class="run-state"><span class="spinner"></span><span>${job.status === "queued" ? tr("Диалог в очереди") : tr("Модель анализирует разговор")} · чек-лист v${esc(job.version)}. Можно продолжить работу.</span></div>` : ""}
 ${stale ? ui`<div class="notice amber" style="margin-bottom:18px">${icon("info")}<p>Эта оценка сделана по v${esc(r.checklist.version)}. Сейчас выбран чек-лист v${esc(active.version)}. ${onlyWeightsChanged(r.checklist, active) ? tr("Ответы можно пересчитать без вызова модели.") : tr("Изменение правил требует нового анализа.")}</p>${onlyWeightsChanged(r.checklist, active) ? ui`<button class="text-btn" data-action="reweight">Пересчитать веса ${icon("refresh", "small")}</button>` : ""}</div>` : ""}
 <div class="source-language-note">${icon("info", "small")}<span>Разговор и основания оценки показаны на исходном языке.</span></div><div class="workspace-grid"><section class="card transcript-panel"><div class="panel-header"><div><h2>Расшифровка</h2><span class="section-meta">Исходные реплики и события</span></div>${pill(duration(d) + tr(" по транскрипту"))}</div>
 ${S.detail.audio ? ui`<div class="audio-player"><div class="audio-caption"><span>${icon("phone", "small")} Запись разговора</span><span>Время записи может отличаться от транскрипта</span></div><audio controls preload="metadata" src="${esc(S.detail.audio)}" aria-label="Запись разговора ${esc(d.conversation_id)}"></audio></div>` : externalAudio ? ui`<div class="audio-player"><a class="text-btn" href="${esc(externalAudio)}" target="_blank" rel="noopener noreferrer">Открыть запись разговора</a></div>` : d.channel === "voice call" ? ui('<div class="audio-player"><span class="muted small">Запись не подключена. Доступен исходный транскрипт.</span></div>') : ""}
 <div class="panel-tools"><div class="search">${icon("search")}<input id="transcript-search" placeholder="Найти в разговоре" aria-label="Поиск по транскрипту" value="${esc(S.transcriptSearch)}"></div><label class="toggle-label"><input type="checkbox" id="context-toggle" ${S.showContext ? "checked" : ""}> Бот и события</label></div><div class="transcript" id="transcript"></div></section>
 <div class="analysis-column">${r ? renderResult(r, history) : `<div class="card">${empty(tr("Диалог готов к оценке"), tr("Выберите действующий чек-лист и запустите анализ. Здесь появятся баллы, объяснения и ссылки на реплики."), "spark", tr("Запустить анализ"), "run-detail")}</div>`}</div></div>${footer()}`;
  renderTranscript();
  renderReviewNavigation();
  updateChrome();
}
function renderTranscript() {
  const d = S.detail.dialogue,
    hidden = d.transcript.filter((m) =>
      ["bot", "system"].includes(m.speaker),
    ).length;
  $("#transcript").innerHTML =
    (!S.showContext && hidden
      ? ui`<button class="context-summary" style="width:100%" data-action="show-context">${icon("eye", "small")} Контекст бота и события · ${hidden} реплик · показать</button>`
      : "") +
    d.transcript
      .map((m, i) => {
        if (!S.showContext && ["bot", "system"].includes(m.speaker)) return "";
        return ui`<article class="message ${m.speaker} ${S.transcriptSearch && m.text.toLowerCase().includes(S.transcriptSearch.toLowerCase()) ? "search-match" : ""}" id="turn-${i + 1}" tabindex="-1"><div class="message-meta"><span class="message-role">${{ client: tr("Клиент"), operator: tr("Оператор"), bot: tr("Бот"), system: tr("Событие") }[m.speaker]}</span><time>${esc(timestamp(m, d))}</time><button class="message-number" data-action="copy-turn" data-value="${i + 1}" title="Скопировать реплику">#${i + 1}</button></div><div class="message-body">${esc(m.text)}</div></article>`;
      })
      .join("");
}
function renderResult(r, history) {
  if (!["completed", "provisional"].includes(r.status))
    return ui`<div class="card score-panel">${empty(tr("Анализ не завершён"), r.error || tr("Результат ещё не получен."), "alert", tr("Повторить анализ"), "run-detail")}<div class="score-history"><span>Предыдущие оценки сохранены</span><select id="evaluation-version" aria-label="Версия оценки">${history.map((h) => `<option value="${esc(h.id)}" ${h.id === r.evaluation_id ? "selected" : ""}>v${esc(h.version)} · ${originName(h.origin)} · ${h.status === "failed" ? tr("ошибка") : h.status === "running" ? tr("выполняется") : tr("с результатом")}</option>`).join("")}</select></div></div>`;
  const score = r.scoring;
  return ui`<section class="card score-panel"><div class="score-overview"><div class="score-ring" style="--score:${Number(score.total_score) || 0}"><div class="ring-content"><b class="mono">${num(score.total_score)}</b><span>из ${num(score.total_max)} баллов</span></div></div><div><h2>Оценка качества</h2><p>${esc(r.model.name)} · ${r.checklist.criteria.length} критериев</p>${r.reviewed ? pill(tr("После пересмотра"), "purple", true) : pill(originName(r.origin), r.origin === "baseline" ? "gray" : "green")}${r.reviewed ? ui`<p style="margin-top:7px;margin-bottom:0">Исходная: ${num(r.original_scoring.total_score)}</p>` : ""}</div></div>
 ${score.gross_violation ? ui`<div class="notice amber" style="margin-top:17px">${icon("alert")}<p>Отмечена грубая ошибка. Флаг учитывается отдельно и не обнуляет итог. <button class="text-btn" data-action="focus-critical">Открыть объяснение ${icon("arrow", "small")}</button></p></div>` : ""}
 ${r.needs_review ? ui`<div class="notice amber" style="margin-top:12px">${icon("info")}<p>Нужна проверка: некоторые внешние факты не подтверждены. Причина указана в соответствующем критерии.</p></div>` : ""}<div class="score-history"><span>История оценок</span><select id="evaluation-version" aria-label="Версия оценки">${history.map((h) => `<option value="${esc(h.id)}" ${h.id === r.evaluation_id ? "selected" : ""}>v${esc(h.version)} · ${originName(h.origin)}${h.status === "provisional" ? tr(" · проверка") : h.status === "failed" ? tr(" · ошибка") : h.status === "running" ? tr(" · выполняется") : ""}</option>`).join("")}</select></div>${r.appeals.length ? ui`<button class="btn outline comparison-entry" data-action="review-comparison" data-evaluation="${esc(r.evaluation_id)}">${icon("scales", "small")} До / после апелляции ${icon("arrow", "small")}</button>` : ""}</section>
 <section class="card criteria-panel"><div class="panel-header"><h2>Критерии оценки</h2><span class="section-meta">Чек-лист v${esc(r.checklist.version)}</span></div>${r.checklist.criteria.map((c) => renderCriterion(c, r)).join("")}</section>
 ${r.limitations?.length ? `<div class="notice amber" style="margin-top:15px">${icon("info")}<p>${r.limitations.map(esc).join("<br>")}</p></div>` : ""}
 ${r.appeals.length ? ui`<section class="card history-card"><h3>История пересмотра</h3>${r.appeals.map((a) => `<div class="history-line">${pill(a.status === "pending" ? tr("На проверке") : tr("Решение сохранено"), a.status === "pending" ? "amber" : "purple")}<span>${esc(a.criterion_id.toUpperCase())} · ${esc(date(a.created_at))}</span><p>${esc(a.comment)}</p>${a.status === "resolved" ? `<p><strong>${esc(answerName(a.original_answer))} → ${esc(answerName(a.answer))}</strong> · ${esc(a.resolution)}</p>` : ui`<button class="text-btn" data-action="resolve" data-id="${esc(a.id)}">Рассмотреть апелляцию ${icon("arrow", "small")}</button>`}</div>`).join("")}</section>` : ""}
 <div class="footer-note"><span>${r.elapsed_seconds ? msg`Время анализа: ${num(r.elapsed_seconds, 1)} с` : tr("Время генерации не указано в сохранённом экспорте")}</span>${r.estimated_cost_usd !== null && r.estimated_cost_usd !== undefined ? `<span>$${num(r.estimated_cost_usd, 5)}</span>` : ""}</div>`;
}
function renderCriterion(c, r) {
  const d = r.decisions[c.id],
    p = r.scoring.criteria.find((p) => p.criterion_id === c.id),
    open = S.openCriteria.has(c.id),
    pending = r.appeals.find(
      (a) => a.criterion_id === c.id && a.status === "pending",
    );
  const color =
    d.answer === "na"
      ? "gray"
      : c.kind === "flag"
        ? d.answer === c.violation_value
          ? "red"
          : "green"
        : Number(p.raw_score) === 0
          ? "amber"
          : "green";
  const answer =
    c.kind === "flag"
      ? d.answer === c.violation_value
        ? tr("Обнаружена")
        : tr("Не обнаружена")
      : c.kind === "scale"
        ? `${answerName(d.answer)} / ${num(c.max_score)}`
        : answerName(d.answer);
  const evidence = d.evidence_turns || [];
  const shortEvidence =
    evidence.length > 8 ? [evidence[0], evidence.at(-1)] : evidence;
  const notes = [...(d.limitations || [])];
  if (d.knowledge_status === "unverified" && !notes.length)
    notes.push(tr("Внешние сведения не подтверждены подходящими источниками."));
  return ui`<article class="criterion ${open ? "open" : ""}" data-criterion="${esc(c.id)}"><button class="criterion-head" data-action="toggle-criterion" data-id="${esc(c.id)}" aria-expanded="${open}"><span class="criterion-index">${esc(c.id.toUpperCase())}</span><span class="criterion-title">${esc(tr(c.title))}</span><span class="criterion-answer">${pill(answer, color)}<span class="sub">${c.kind === "flag" ? tr("Без баллов") : d.answer === "na" ? tr("Вес перераспределён") : num(p.points) + tr(" балла")}</span></span>${icon("down", "chevron")}</button><div class="criterion-body"><p class="reason">${esc(d.reason)}</p>
 <div class="evidence-list">${shortEvidence.map((n) => ui`<button class="evidence-btn" data-action="evidence" data-turn="${n}" data-criterion-id="${esc(c.id)}">${icon("link")} Реплика ${n}</button>`).join("")}${evidence.length > 8 ? ui`<span class="section-meta" style="font-size:9px">Проверен диапазон ${evidence[0]}–${evidence.at(-1)}</span>` : ""}</div>
 ${notes.length ? `<div class="criterion-limit">${notes.map(esc).join("<br>")}</div>` : ""}
 ${d.knowledge_status && ["supported", "contradicted"].includes(d.knowledge_status) ? `<div style="margin-top:10px">${pill(d.knowledge_status === "supported" ? tr("Подтверждено источником") : tr("Противоречит источнику"), d.knowledge_status === "supported" ? "green" : "amber")}</div>` : ""}
 ${(d.source_ids || [])
   .map((id) => {
     const src = (r.knowledge_sources || []).find((s) => s.id === id);
     return src
       ? `<details class="rule-details"><summary>${esc(src.title)}</summary><div class="source-item">${esc(src.text)}</div></details>`
       : "";
   })
   .join("")}
 <details class="rule-details"><summary>Правило и расчёт</summary><p>${esc(c.rule)}</p><p>Исходный вес: ${num(c.weight)}. ${c.kind === "flag" ? tr("Флаг не влияет на итоговый балл.") : msg`Вес после N/A: ${num(p.effective_weight)}. Вклад: ${num(p.points)}.`}</p>${d.answer === "na" ? ui`<p>Основание N/A: ${esc(c.na_conditions.find((n) => n.id === d.na_condition_id)?.description || tr("Указано в объяснении"))}</p>` : ""}</details>
 <div class="criterion-actions">${d.reviewed_by ? pill(tr("Решение проверяющего"), "purple") : ""}${pending ? pill(tr("Апелляция на проверке"), "amber") : ui`<button class="text-btn" data-action="appeal" data-id="${esc(c.id)}">${icon("scales", "small")} Оспорить оценку</button>`}<span class="section-meta" style="font-size:9px">${c.kind === "flag" ? tr("Отдельный флаг") : tr("Вес ") + num(c.weight)}</span></div></div></article>`;
}
function jumpEvidence(turn, key) {
  const r = S.detail.result,
    evidence = key ? r?.decisions[key]?.evidence_turns || [turn] : [turn];
  if (
    evidence.some((n) =>
      ["bot", "system"].includes(S.detail.dialogue.transcript[n - 1]?.speaker),
    )
  ) {
    S.showContext = true;
    $("#context-toggle").checked = true;
    renderTranscript();
  }
  $$(".message.highlight").forEach((e) => e.classList.remove("highlight"));
  evidence.forEach((n) => $("#turn-" + n)?.classList.add("highlight"));
  const el = $("#turn-" + turn);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.focus({ preventScroll: true });
  }
}
function renderAppeals() {
  const all = S.data.appeals,
    rows = all.filter(
      (a) => S.appealFilter === "all" || a.status === S.appealFilter,
    );
  $("#main").innerHTML =
    ui`<div class="page-head"><div><div class="eyebrow">ОТ СПОРНОЙ ОЦЕНКИ К РЕШЕНИЮ</div><h1>Апелляции</h1><p>Контекст, аргументы и история каждого пересмотра.</p></div>${pill(all.filter((a) => a.status === "pending").length + tr(" на проверке"), "purple", true)}</div><div class="appeal-controls tabs" style="width:max-content">${[
      ["pending", tr("На проверке")],
      ["resolved", tr("Рассмотрены")],
      ["all", tr("Все")],
    ]
      .map(
        ([v, t]) =>
          `<button class="tab ${S.appealFilter === v ? "active" : ""}" data-action="appeal-filter" data-value="${v}">${t}</button>`,
      )
      .join("")}</div>${
      rows.length
        ? rows
            .map((a) => {
              const c = S.data.checklists
                .find((c) => c.version === a.checklist_version)
                ?.criteria.find((c) => c.id === a.criterion_id);
              return ui`<article class="card appeal-card"><div class="channel-icon" style="background:var(--purple);color:var(--purple-ink)">${icon("scales")}</div><div class="appeal-main"><div class="between"><h3>${esc(tr(c?.title || a.criterion_id.toUpperCase()))}</h3>${pill(a.status === "pending" ? tr("На проверке") : tr("Рассмотрена"), a.status === "pending" ? "amber" : "green", true)}</div><div class="appeal-meta" style="margin-top:7px"><a href="${conversationHref(a.conversation_id, a.evaluation_id)}">${esc(a.conversation_id)} ${icon("upRight", "small")}</a><span>v${esc(a.checklist_version)}</span><span>${esc(date(a.created_at))}</span></div><p>${esc(a.comment)}</p><div class="appeal-meta"><span>Исходная оценка: <strong>${esc(answerName(a.original_answer))}</strong></span><span>Автор: ${esc(a.actor)}</span></div>${a.status === "resolved" ? `<div class="appeal-resolution">${pill(answerName(a.original_answer) + " → " + answerName(a.answer), "purple")} <strong>${esc(a.reviewer)}</strong><br>${esc(a.resolution)}</div>` : ""}</div><div class="actions appeal-card-actions"><button class="btn outline sm" data-action="review-comparison" data-evaluation="${esc(a.evaluation_id)}" data-appeal="${esc(a.id)}">До / после</button><button class="btn ${a.status === "pending" ? "primary" : "outline"} sm" data-action="resolve" data-id="${esc(a.id)}">${a.status === "pending" ? tr("Рассмотреть") : tr("Открыть решение")} ${icon("arrow", "small")}</button></div></article>`;
            })
            .join("")
        : `<section class="card">${empty(S.appealFilter === "pending" ? tr("Нет открытых апелляций") : tr("Здесь появятся решения"), tr("Откройте диалог и нажмите «Оспорить оценку» у конкретного критерия. Все аргументы и решения сохраняются."), "scales", tr("Перейти к диалогам"), "go-dialogues")}</section>`
    }${footer()}`;
}
function appealModal(key) {
  const r = S.detail.result,
    c = r.checklist.criteria.find((c) => c.id === key),
    d = r.decisions[key];
  openModal(
    tr("Оспорить оценку"),
    `${S.detail.dialogue.conversation_id} · ${key.toUpperCase()}`,
    ui`<h3>${esc(tr(c.title))}</h3><div style="margin-top:10px">${pill(tr("Исходный ответ: ") + answerName(d.answer), "purple")}</div><div class="modal-quote">${esc(d.reason)}</div><div class="field"><label for="appeal-comment">Почему оценку нужно пересмотреть?</label><textarea id="appeal-comment" name="comment" required minlength="3" maxlength="5000" rows="4" placeholder="Опишите, что не учла оценка. При необходимости укажите номера реплик."></textarea><p class="form-help">Проверяющий увидит ваш комментарий, исходную оценку и диалог.</p></div><input type="hidden" name="criterion_id" value="${esc(key)}"><input type="hidden" name="evaluation_id" value="${esc(r.evaluation_id)}">`,
    ui`${cancelButton()}<button class="btn primary" type="submit">Отправить на проверку ${icon("arrow", "small")}</button>`,
    "appeal-form",
  );
}
async function resolveModal(id) {
  const a = S.data.appeals.find((a) => a.id === id);
  if (!a) return;
  const detail = await api(
    `/ui-api/conversations/${encodeURIComponent(a.conversation_id)}?evaluation_id=${encodeURIComponent(a.evaluation_id)}`,
  );
  const c = detail.result.checklist.criteria.find(
      (c) => c.id === a.criterion_id,
    ),
    d = detail.result.original_decisions[a.criterion_id];
  S.resolving = { appeal: a, detail, criterion: c };
  const done = a.status === "resolved",
    can = S.role === "reviewer";
  const options = c.options
    .map(
      (o) =>
        `<option value="${esc(o.value)}" ${o.value === (a.answer || a.original_answer) ? "selected" : ""}>${esc(answerName(o.value))} — ${esc(o.description)}</option>`,
    )
    .join("");
  const na = c.na_conditions.filter(
    (n) => !n.channels || n.channels.includes(detail.dialogue.channel),
  );
  openModal(
    done ? tr("Решение по апелляции") : tr("Рассмотрение апелляции"),
    `${a.conversation_id} · ${a.criterion_id.toUpperCase()} · v${a.checklist_version}`,
    ui`<h3>${esc(tr(c.title))}</h3><p class="small muted" style="margin-top:13px">Аргумент автора</p><div class="modal-quote">${esc(a.comment)}</div><details class="rule-details"><summary>Оценка на момент апелляции и доказательства</summary><p>${esc(a.original_reason)}</p><p>${(d.evidence_turns || []).map((n) => `<b>#${n}</b> ${esc(detail.dialogue.transcript[n - 1]?.text || "")}`).join("<br>")}</p></details><div class="spacer"></div>${done ? `<div class="appeal-resolution"><strong>${esc(answerName(a.original_answer))} → ${esc(answerName(a.answer))}</strong><p>${esc(a.resolution)}</p><p class="form-help">${esc(a.reviewer)} · ${esc(date(a.resolved_at))}</p></div>` : !can ? ui('<div class="notice amber">Для принятия решения переключитесь в роль проверяющего. Апелляция останется в очереди.</div>') : ui`<div class="field"><label for="resolve-answer">Решение проверяющего</label><select name="answer" id="resolve-answer">${options}${na.length ? ui`<option value="na" ${a.original_answer === "na" ? "selected" : ""}>N/A — критерий неприменим</option>` : ""}</select></div>${na.length ? ui`<div class="field" id="resolve-na-field" ${a.original_answer !== "na" ? "hidden" : ""}><label for="resolve-na">Условие неприменимости</label><select name="na_condition_id" id="resolve-na">${na.map((n) => `<option value="${esc(n.id)}">${esc(n.description)}</option>`).join("")}</select></div>` : ""}<div class="field"><label for="resolve-reason">Основание решения</label><textarea id="resolve-reason" name="reason" required minlength="3" maxlength="5000" rows="4" placeholder="Объясните, почему исходная оценка подтверждена или изменена."></textarea></div><input type="hidden" name="appeal_id" value="${esc(id)}">`}`,
    ui`<button type="button" class="btn outline" data-action="open-appeal-dialogue" data-id="${esc(a.conversation_id)}" data-evaluation="${esc(a.evaluation_id)}">Открыть диалог</button><button type="button" class="btn outline" data-action="review-comparison" data-evaluation="${esc(a.evaluation_id)}" data-appeal="${esc(a.id)}">До / после</button>${done ? ui('<button type="button" class="btn primary" data-action="close-modal">Готово</button>') : can ? ui('<button type="submit" class="btn primary">Сохранить решение</button>') : ui('<button type="button" class="btn primary" data-action="switch-reviewer">Стать проверяющим</button>')}`,
    "resolution-form",
  );
}

function nextVersion(c) {
  let n = 1;
  while (
    S.data.checklists.some(
      (x) => x.id === c.id && x.version === `${c.version}-ui.${n}`,
    )
  )
    n++;
  return `${c.version}-ui.${n}`;
}
function renderChecklists() {
  if (!S.checklist) S.checklist = activeChecklist();
  if (!S.draft) {
    S.draft = structuredClone(S.checklist);
    S.draft.version = nextVersion(S.checklist);
    S.dirty = false;
  }
  const c = S.draft,
    active = S.data.active_checklist,
    selected = S.checklist,
    can = S.role === "reviewer";
  $("#main").innerHTML =
    ui`<div class="page-head"><div><div class="eyebrow">ПОНЯТНЫЕ ПРАВИЛА · ВОСПРОИЗВОДИМЫЕ ОЦЕНКИ</div><h1>Чек-листы</h1><p>Меняйте правила через интерфейс. Каждая версия сохраняется отдельно.</p></div><div class="actions"><button type="button" class="btn outline" data-action="compare-checklists">${icon("scales", "small")} Сравнить версии</button>${pill(tr("Действующая v") + active.version, "green", true)}</div></div><div class="checklist-layout"><aside class="card version-panel"><h3>СОХРАНЁННЫЕ ВЕРСИИ</h3>${[
      ...S.data.checklists,
    ]
      .reverse()
      .map(
        (x, i) =>
          ui`<button class="version-item ${x.id === selected.id && x.version === selected.version ? "active" : ""}" data-action="choose-checklist" data-index="${S.data.checklists.indexOf(x)}"><strong>v${esc(x.version)}</strong>${x.id === active.id && x.version === active.version ? pill(tr("Активна"), "green") : ""}<small>${esc(x.title)}<br>${x.criteria.length} критериев</small></button>`,
      )
      .join(
        "",
      )}</aside><div class="checklist-main"><form id="checklist-form" class="card"><div class="checklist-editor"><div class="between" style="margin-bottom:22px"><div><h2>Правила оценки</h2><p class="form-help">Основа: v${esc(selected.version)}. Исходная версия останется в истории.</p></div>${selected.version !== active.version || selected.id !== active.id ? ui`<button type="button" class="btn outline sm" data-action="activate-checklist">Применять эту версию</button>` : pill(tr("Используется"), "green")}</div>${!can ? ui('<div class="notice amber" style="margin-bottom:20px">Редактирование доступно в роли проверяющего.</div>') : ""}<fieldset ${!can ? "disabled" : ""} style="border:0;margin:0;padding:0"><div class="form-grid"><div><label for="checklist-title">Название чек-листа</label><input id="checklist-title" data-checklist-field="title" value="${esc(c.title)}" required maxlength="180"></div><div><label for="checklist-version">Новая версия</label><input id="checklist-version" data-checklist-field="version" value="${esc(c.version)}" required maxlength="80"></div></div><div class="checklist-summary" id="checklist-summary"></div><div id="editor-criteria">${c.criteria.map((x, i) => editCriterion(x, i)).join("")}</div><div class="editor-footer"><button type="button" class="btn outline sm" data-action="add-criterion">${icon("plus", "small")} Добавить критерий</button><span class="form-help">До 50 критериев</span></div><div class="spacer"></div><div class="notice">${icon("info")}<p>Новая формулировка или шкала требуют повторного анализа. Если изменились только веса, ответы можно пересчитать без вызова модели.</p></div></fieldset><div id="checklist-error" hidden></div></div><div class="sticky-actions"><span class="form-help" id="draft-status">Исходные оценки не изменятся</span><div class="actions"><button type="button" class="btn outline" data-action="reset-draft">Сбросить</button><button type="submit" class="btn primary" ${!can ? "disabled" : ""}>${icon("check", "small")} Сохранить новую версию</button></div></div></form></div></div>${footer()}`;
  updateDraftSummary();
}
function editCriterion(c, i) {
  return ui`<details class="edit-criterion" data-edit-index="${i}" ${i === S.draft.criteria.length - 1 && S.justAdded ? "open" : ""}><summary><span class="criterion-index">${esc(c.id.toUpperCase())}</span><span data-edit-title="${i}">${esc(c.title || tr("Новый критерий"))}</span>${pill(c.kind === "flag" ? tr("Флаг") : tr("Вес ") + num(c.weight))}${icon("down", "chevron")}</summary><div class="edit-fields"><div class="form-grid"><div><label>Название</label><input required maxlength="180" aria-label="Название" data-ci="${i}" data-field="title" value="${esc(c.title)}"></div><div><label>Раздел</label><input required aria-label="Раздел" data-ci="${i}" data-field="section" value="${esc(c.section)}"></div></div><div class="spacer"></div><div class="form-grid three"><div><label>Код критерия</label><input required pattern="[A-Za-z][A-Za-z0-9_-]{0,63}" aria-label="Код критерия" data-ci="${i}" data-field="id" value="${esc(c.id)}"></div><div><label>Тип ответа</label><select aria-label="Тип ответа" data-ci="${i}" data-field="kind">${[
    ["binary", tr("Да / Нет")],
    ["scale", tr("Шкала")],
    ["flag", tr("Грубая ошибка")],
  ]
    .map(
      ([v, t]) =>
        `<option value="${v}" ${c.kind === v ? "selected" : ""}>${t}</option>`,
    )
    .join(
      "",
    )}</select></div><div><label>Вес</label><input type="number" required min="0" max="1000" step="any" aria-label="Вес" data-ci="${i}" data-field="weight" value="${esc(c.weight)}" ${c.kind === "flag" ? "readonly" : ""}></div><div class="full"><label>Что именно оценивать</label><textarea required rows="4" aria-label="Что именно оценивать" data-ci="${i}" data-field="rule" placeholder="Опишите условия выполнения, нарушения и исключения.">${esc(c.rule)}</textarea></div></div><div class="spacer"></div><label>Варианты ответа и условия</label>${c.options.map((o, j) => ui`<div class="option-row"><input aria-label="Баллы варианта ${j + 1}" type="number" min="0" step="0.5" data-ci="${i}" data-option="${j}" data-option-field="raw_score" value="${esc(o.raw_score)}" ${c.kind !== "scale" ? "readonly" : ""}><input aria-label="Описание варианта ${j + 1}" required data-ci="${i}" data-option="${j}" data-option-field="description" value="${esc(o.description)}">${c.kind === "scale" ? ui`<button type="button" class="icon-btn" data-action="remove-option" data-ci="${i}" data-oi="${j}" aria-label="Удалить вариант" ${c.options.length <= 2 ? "disabled" : ""}>${icon("close", "small")}</button>` : "<span></span>"}</div>`).join("")}${c.kind === "scale" ? ui`<button type="button" class="text-btn" data-action="add-option" data-ci="${i}">${icon("plus", "small")} Добавить ступень</button>` : ""}<div class="spacer"></div><label class="toggle-label" style="font-size:11px"><input type="checkbox" data-ci="${i}" data-field="allow_na" ${c.na_conditions.length ? "checked" : ""}> Разрешить N/A при заданном условии</label>${c.na_conditions.map((n, j) => ui`<div style="margin-top:10px"><label>Условие N/A ${c.na_conditions.length > 1 ? j + 1 : ""}</label><textarea required rows="2" aria-label="Условие N/A ${j + 1}" data-ci="${i}" data-na="${j}">${esc(n.description)}</textarea>${n.channels ? ui`<p class="form-help">Каналы: ${n.channels.map((x) => (x === "voice call" ? tr("звонок") : tr("чат"))).join(", ")}</p>` : ""}</div>`).join("")}<label class="toggle-label" style="font-size:11px;margin-top:17px"><input type="checkbox" data-ci="${i}" data-field="requires_company_knowledge" ${c.requires_company_knowledge ? "checked" : ""}> Для проверки нужны знания компании</label>${c.requires_company_knowledge ? ui`<div class="field"><label for="fact-limit-${i}">Максимум наблюдаемых фактов</label><input type="number" min="1" step="1" id="fact-limit-${i}" data-ci="${i}" data-field="max_observed_facts" value="${esc(c.max_observed_facts)}" placeholder="Без ограничения"></div>` : ""}<div class="editor-footer"><span class="form-help">${c.kind === "flag" ? tr("Нарушение отмечается при ответе «Да». Флаг не обнуляет итог.") : tr("Верхняя ступень даёт полный вес критерия.")}</span><button type="button" class="text-btn" style="color:var(--red)" data-action="remove-criterion" data-ci="${i}" ${S.draft.criteria.length <= 1 ? "disabled" : ""}>${icon("trash", "small")} Удалить</button></div></div></details>`;
}
function updateDraftSummary() {
  const c = S.draft;
  if (!c) return;
  const el = $("#checklist-summary");
  if (el)
    el.innerHTML = ui`<span><b>${c.criteria.length}</b> критериев</span><span><b>${num(c.criteria.reduce((s, x) => s + Number(x.weight), 0))}</b> сумма весов</span><span><b>${num(c.total_max)}</b> максимум после нормировки</span>`;
  const status = $("#draft-status");
  if (status)
    status.textContent = S.dirty
      ? tr("Есть несохранённые изменения")
      : tr("Исходные оценки не изменятся");
}
function renderEditorCriteria() {
  const open = new Set(
    $$(".edit-criterion[open]").map((e) => e.dataset.editIndex),
  );
  $("#editor-criteria").innerHTML = S.draft.criteria
    .map(editCriterion)
    .join("");
  open.forEach((i) => $(`[data-edit-index="${i}"]`)?.setAttribute("open", ""));
  S.justAdded = false;
  updateDraftSummary();
}
function renderAnalytics() {
  const rows = S.data.conversations,
    m = metrics(),
    rated = rows.filter((r) => r.score !== null),
    bins = [0, 0, 0, 0, 0];
  rated.forEach((r) => bins[Math.min(4, Math.floor(Number(r.score) / 20))]++);
  const max = Math.max(1, ...bins);
  const criteria = new Map();
  const versions = new Set(rated.map((r) => r.version));
  rated.forEach((r) =>
    r.criteria.forEach((c) => {
      if (c.answer === "na" || c.points === null) return;
      const key = r.version + ":" + c.criterion_id;
      const item = criteria.get(key) || {
        title: tr(c.title) + (versions.size > 1 ? ` · v${r.version}` : ""),
        sum: 0,
        count: 0,
      };
      item.sum += (Number(c.raw_score) / Number(c.max_score)) * 100;
      item.count++;
      criteria.set(key, item);
    }),
  );
  $("#main").innerHTML =
    ui`<div class="page-head"><div><div class="eyebrow">ОБЩАЯ КАРТИНА</div><h1>Аналитика качества</h1><p>Распределение оценок и зоны внимания в загруженных разговорах.</p></div><button class="btn outline" data-action="export">${icon("download", "small")} Выгрузить результаты</button></div>${statCards()}${versions.size > 1 ? ui`<div class="notice amber" style="margin-bottom:20px">${icon("info")}<p>В выборке ${versions.size} версии чек-листа. Итоги рассчитаны по разным правилам; выполнение критериев показано отдельно по версиям.</p></div>` : ""}<div class="chart-grid"><section class="card chart-card"><h2>Распределение оценок</h2><p class="chart-caption">Последняя оценка каждого диалога, включая сохранённые решения по апелляциям</p><div class="histogram">${bins.map((n, i) => `<div class="hist-bar" style="height:${Math.max(2, (n / max) * 135)}px"><b>${n}</b><small>${i * 20}–${i === 4 ? "100" : i * 20 + 19}</small></div>`).join("")}</div><div class="notice" style="margin-top:18px">${icon("info")}<p>Распределение описывает оценки разговоров. Точность модели требует сравнения с независимой ручной разметкой.</p></div></section><section class="card chart-card"><h2>По языкам</h2><p class="chart-caption">Средний балл и число оценённых разговоров</p>${[
      "RU",
      "KZ",
      "EN",
    ]
      .map((l) => {
        const subset = rows.filter((r) => r.language === l),
          lm = metrics(subset);
        return ui`<div class="language-card"><span class="lang-square">${l}</span><div class="language-title"><strong>${langName(l)}</strong><small>${lm.rated} из ${lm.total} оценено · ${lm.critical} с грубыми ошибками</small></div><span class="language-score mono">${num(lm.avg, 1)}</span></div>`;
      })
      .join(
        "",
      )}</section><section class="card chart-card"><h2>Выполнение критериев</h2><p class="chart-caption">Средняя доля от максимума шкалы · N/A исключены</p>${[...criteria.values()].map((c) => `<div class="metric-row"><span>${esc(c.title)}</span><div class="bar"><i style="width:${c.sum / c.count}%"></i></div><b>${num(c.sum / c.count, 0)}%</b></div>`).join("") || ui('<p class="muted small">Появится после первой оценки.</p>')}</section><section class="card chart-card"><h2>Пересмотр оценок</h2><p class="chart-caption">Решения людей сохраняются вместе с исходным результатом</p><div class="info-grid"><div class="info-cell"><small>Открытых апелляций</small><h2>${m.pending}</h2></div><div class="info-cell"><small>Рассмотрено</small><h2>${S.data.appeals.filter((a) => a.status === "resolved").length}</h2></div><div class="info-cell"><small>Оценка изменена</small><h2>${S.data.appeals.filter((a) => a.status === "resolved" && a.answer !== a.original_answer).length}</h2></div><div class="info-cell"><small>Оценка подтверждена</small><h2>${S.data.appeals.filter((a) => a.status === "resolved" && a.answer === a.original_answer).length}</h2></div></div><button class="btn outline" style="margin-top:23px" data-action="go-appeals">Открыть апелляции ${icon("arrow", "small")}</button></section></div>${footer()}`;
}
function importModal() {
  S.importPayload = null;
  openModal(
    tr("Загрузить диалоги"),
    tr("JSON организаторов, массив диалогов или один разговор"),
    ui`<label class="dropzone" id="dropzone">${icon("upload")}<strong>Выберите файл или перетащите его сюда</strong><small>JSON · до 15 МБ · RU, KZ, EN</small><input type="file" id="import-file" accept=".json,application/json" aria-label="Выбрать JSON с диалогами"></label><div id="file-preview"></div><details class="rule-details" style="margin-top:18px"><summary>Или вставьте JSON</summary><textarea id="import-json" rows="5" style="margin-top:12px;font-size:11px" placeholder='{"conversation_id":"new-001", ...}' aria-label="Содержимое JSON"></textarea></details><div class="notice" style="margin-top:20px">${icon("info")}<p>Исходные реплики сохранятся без изменений. Загрузка не запускает модель автоматически.</p></div>`,
    ui`${cancelButton()}<button class="btn primary" type="submit" id="import-submit">Загрузить диалоги ${icon("arrow", "small")}</button>`,
    "import-form",
  );
}
function inspectImport(text, name) {
  try {
    const data = JSON.parse(text.replace(/^\uFEFF/, ""));
    const rows = Array.isArray(data) ? data : data?.data?.records || [data];
    if (
      !Array.isArray(rows) || !rows.length ||
      rows.some((r) => !r?.conversation_id || !Array.isArray(r.transcript))
    )
      throw new Error(tr("Ожидаются conversation_id и массив transcript."));
    S.importPayload = { data, ids: rows.map((r) => r.conversation_id) };
    $("#file-preview").innerHTML =
      ui`<div class="file-preview">${icon("file", "small")} <strong>${esc(name)}</strong><br>${rows.length} диалогов · ${[...new Set(rows.map((r) => r.language))].map(esc).join(", ")}<p class="form-help">Окончательная проверка формата будет выполнена сервером.</p></div>`;
    $("#modal-error").hidden = true;
    return true;
  } catch (e) {
    S.importPayload = null;
    $("#file-preview").replaceChildren();
    modalError(tr("Не удалось прочитать JSON: ") + e.message);
    return false;
  }
}
async function importFile(file) {
  if (!file) return;
  S.importPayload = null;
  const preview = $("#file-preview");
  const read = Symbol();
  preview.fileRead = read;
  preview.replaceChildren();
  $("#import-json").value = "";
  if (file.size > 15_000_000) {
    modalError(tr("Максимальный размер файла — 15 МБ"));
    return;
  }
  try {
    const text = await file.text();
    if ($("#file-preview") === preview && preview.fileRead === read) inspectImport(text, file.name);
  } catch {
    if ($("#file-preview") === preview && preview.fileRead === read) modalError(tr("Не удалось прочитать файл."));
  }
}
function exportModal(ids) {
  S.exportEvaluations =
    ids && S.detail?.result
      ? { [S.detail.dialogue.conversation_id]: S.detail.result.evaluation_id }
      : {};
  S.exportIds =
    ids || (S.selected.size ? [...S.selected] : filtered().map((r) => r.id));
  openModal(
    tr("Выгрузить результаты"),
    msg`${S.exportIds.length} диалогов в выбранном наборе`,
    ui`<label class="radio-option"><input type="radio" name="format" value="report" checked><span>Рабочий отчёт<small>Исходные оценки, решения по апелляциям, версии и доказательства.</small></span></label><label class="radio-option"><input type="radio" name="format" value="submission"><span>Для жюри · JSON 1.0<small>Исходные ответы модели. Полный DEV (65) или PROD (10), единая версия чек-листа. Без дополнительных полей.</small></span></label><div class="form-grid" style="margin-top:19px"><div><label for="export-team">Название команды</label><input id="export-team" name="team_name" value="${esc(localStorage.getItem("cqa-team") || "Status")}" required maxlength="100"></div><div><label for="export-dataset">Набор</label><select id="export-dataset" name="dataset"><option value="dev">DEV · 65 диалогов</option><option value="prod">PROD · 10 чатов</option></select></div></div><p class="form-help" style="margin-top:15px">Экспорт содержит выбранные диалоги. Если выбор пуст — все результаты текущего фильтра.</p>`,
    ui`${cancelButton()}<button class="btn primary" type="submit">${icon("download", "small")} Скачать JSON</button>`,
    "export-form",
  );
}
function download(data, name) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function modelInfo() {
  S.model = await api("/ui-api/model");
  updateChrome();
  const m = S.model;
  openModal(
    tr("Подключение модели"),
    tr("Статус сервера для новых оценок"),
    ui`<div class="notice ${m.ready ? "" : "amber"}">${icon(m.ready ? "check" : "info")}<p>${esc(tr(m.detail))}</p></div><div class="info-grid"><div class="info-cell"><small>Модель</small>${esc(m.name)}</div><div class="info-cell"><small>Провайдер</small>${esc(m.provider)}</div><div class="info-cell"><small>Тайм-аут запроса</small>${num(m.timeout_seconds, 0)} секунд</div><div class="info-cell"><small>Учёт расходов</small>${esc(tr(m.billing))}</div></div><p class="form-help" style="margin-top:19px">Настройки берутся из файла, указанного при запуске сервера через --settings. Ключи остаются на сервере. Инструкция: docs/ui-workspace.md.</p><p class="form-help">Сохранённые результаты, апелляции и редактор чек-листа доступны независимо от соединения с моделью.</p>`,
    ui`<button type="button" class="btn outline" data-action="model-info">${icon("refresh", "small")} Проверить снова</button><button class="btn primary" type="button" data-action="close-modal">Понятно</button>`,
  );
}
function jobsModal() {
  openModal(
    tr("Очередь анализа"),
    tr("Задания и их фактическое состояние"),
    S.data.jobs.length
      ? S.data.jobs
          .map(
            (j) =>
              `<div class="job-row"><span>${j.status === "running" ? '<span class="spinner" style="width:16px;height:16px"></span>' : icon(j.status === "completed" ? "check" : j.status === "failed" ? "alert" : "clock", "small")}</span><div class="job-info"><a href="#/dialogues?id=${encodeURIComponent(j.conversation_id)}" data-action="open-appeal-dialogue" data-id="${esc(j.conversation_id)}">${esc(j.conversation_id)}</a><small>v${esc(j.version)} · ${esc(date(j.created_at))}</small>${j.error ? `<small class="job-error">${esc(j.error)}</small>` : ""}</div><span class="job-status">${{ queued: tr("В очереди"), running: tr("Выполняется"), completed: tr("Готово"), failed: tr("Ошибка"), interrupted: tr("Прервано") }[j.status] || esc(j.status)}</span></div>`,
          )
          .join("")
      : empty(
          tr("Очередь пуста"),
          tr(
            "Откройте диалог и запустите оценку. Несколько выбранных разговоров можно поставить в очередь из списка.",
          ),
          "clock",
        ),
    ui(
      '<button class="btn primary" type="button" data-action="close-modal">Готово</button>',
    ),
  );
}
async function runDialogues(ids) {
  if (!ids.length) {
    toast(tr("Выберите хотя бы один диалог"), true);
    return;
  }
  S.runIds = ids;
  S.model = await api("/ui-api/model");
  updateChrome();
  if (!S.model.ready) {
    await modelInfo();
    return;
  }
  const c = activeChecklist();
  openModal(
    ids.length === 1
      ? tr("Запустить анализ?")
      : tr("Оценить выбранные диалоги"),
    msg`${ids.length} диалогов · ${S.model.name}`,
    ui`<div class="field"><label for="run-checklist">Чек-лист</label><select name="checklist" id="run-checklist">${S.data.checklists.map((x, i) => `<option value="${i}" ${x.id === c.id && x.version === c.version ? "selected" : ""}>v${esc(x.version)} · ${esc(x.title)}</option>`).join("")}</select></div><div class="notice">${icon("info")}<p>Будет выполнен новый вызов модели для каждого диалога. Предыдущие оценки и апелляции сохранятся в истории. ${esc(tr(S.model.billing))}.</p></div>`,
    ui`${cancelButton()}<button class="btn primary" type="submit">${icon("play", "small")} Начать анализ</button>`,
    "run-form",
  );
}
async function reloadDetail() {
  if (!S.detail) return;
  const id = S.detail.dialogue.conversation_id;
  const hash = location.hash;
  const evaluation = new URLSearchParams(hash.split("?")[1] || "").get(
    "evaluation_id",
  );
  const detail = await api(
    "/ui-api/conversations/" +
      encodeURIComponent(id) +
      (evaluation ? "?evaluation_id=" + encodeURIComponent(evaluation) : ""),
  );
  if (location.hash !== hash) return;
  S.detail = detail;
  renderDetail();
}

document.addEventListener("click", async (event) => {
  const b = event.target.closest("[data-action]");
  if (!b || b.disabled) return;
  const action = b.dataset.action;
  try {
    switch (action) {
      case "start-review":
        await startReview();
        break;
      case "start-review-detail":
        await startReview(true);
        break;
      case "review-next":
        await moveReview(1);
        break;
      case "review-previous":
        await moveReview(-1);
        break;
      case "leave-review":
        event.preventDefault();
        leaveReview();
        break;
      case "compare-checklists":
        openChecklistComparison();
        break;
      case "validate-draft":
        $("#modal").addEventListener(
          "close",
          () => $("#checklist-form")?.reportValidity(),
          { once: true },
        );
        closeModal();
        break;
      case "review-comparison":
        await openReviewComparison(
          b.dataset.evaluation,
          b.dataset.appeal || null,
        );
        break;
      case "comparison-evidence": {
        const { conversation, evaluation, turn } = b.dataset;
        closeModal();
        if (S.detail?.result?.evaluation_id === evaluation)
          jumpEvidence(Number(turn));
        else
          location.hash = conversationHref(
            conversation,
            evaluation,
            false,
            turn,
          );
        break;
      }
      case "toggle-theme":
        CqaI18n.setTheme(CqaI18n.theme === "dark" ? "light" : "dark");
        updatePreferences();
        break;
      case "close-modal":
        closeModal();
        break;
      case "go-dialogues":
        location.hash = "/dialogues";
        break;
      case "go-appeals":
        location.hash = "/appeals";
        break;
      case "filter-critical":
        S.filter = "critical";
        S.q = "";
        S.language = S.channel = "all";
        S.offset = 0;
        if (S.page !== "dialogues" || S.detail) {
          location.hash = "/dialogues";
        } else renderDialogues();
        break;
      case "filter":
        S.filter = b.dataset.value;
        S.offset = 0;
        renderDialogues();
        break;
      case "reset-filters":
        S.q = "";
        S.language = S.channel = S.filter = "all";
        S.offset = 0;
        renderDialogues();
        break;
      case "page":
        S.offset = Number(b.dataset.value);
        renderTable();
        break;
      case "sort-score":
        S.sort = S.sort === "score" ? "id" : "score";
        S.offset = 0;
        renderTable();
        break;
      case "clear-selection":
        S.selected.clear();
        renderTable();
        break;
      case "focus-critical": {
        const c = S.detail.result.checklist.criteria.find(
          (c) =>
            c.kind === "flag" &&
            S.detail.result.decisions[c.id].answer === c.violation_value,
        );
        if (c) {
          S.openCriteria.add(c.id);
          renderDetail();
          $(`[data-criterion="${c.id}"]`).scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
        }
        break;
      }
      case "toggle-criterion": {
        const k = b.dataset.id;
        S.openCriteria.has(k)
          ? S.openCriteria.delete(k)
          : S.openCriteria.add(k);
        const article = b.closest(".criterion");
        article.classList.toggle("open");
        b.setAttribute("aria-expanded", article.classList.contains("open"));
        break;
      }
      case "evidence":
        jumpEvidence(Number(b.dataset.turn), b.dataset.criterionId);
        break;
      case "show-context":
        S.showContext = true;
        $("#context-toggle").checked = true;
        renderTranscript();
        break;
      case "copy-turn": {
        const n = Number(b.dataset.value);
        await navigator.clipboard.writeText(
          `#${n} ${S.detail.dialogue.transcript[n - 1].text}`,
        );
        toast(tr("Реплика скопирована"));
        break;
      }
      case "appeal":
        appealModal(b.dataset.id);
        break;
      case "resolve":
        await resolveModal(b.dataset.id);
        break;
      case "open-appeal-dialogue":
        event.preventDefault();
        closeModal();
        location.hash = conversationHref(b.dataset.id, b.dataset.evaluation);
        break;
      case "switch-reviewer":
        S.role = "reviewer";
        try {
          localStorage.setItem("cqa-role", S.role);
        } catch {
          /* Continue without persistence. */
        }
        $("#role").value = S.role;
        updatePreferences();
        updateChrome();
        await resolveModal(S.resolving.appeal.id);
        break;
      case "appeal-filter":
        S.appealFilter = b.dataset.value;
        renderAppeals();
        break;
      case "choose-checklist":
        if (S.dirty) {
          S.pendingChecklist = Number(b.dataset.index);
          openModal(
            tr("Сменить версию?"),
            tr("В текущем черновике есть несохранённые изменения."),
            ui(
              "<p>При переходе к другой версии этот черновик будет сброшен.</p>",
            ),
            ui`${cancelButton()}<button type="button" class="btn primary" data-action="discard-and-switch">Перейти без сохранения</button>`,
          );
          break;
        }
        S.checklist = S.data.checklists[Number(b.dataset.index)];
        S.draft = null;
        renderChecklists();
        break;
      case "discard-and-switch":
        closeModal();
        S.checklist = S.data.checklists[S.pendingChecklist];
        S.draft = null;
        renderChecklists();
        break;
      case "reset-draft":
        S.draft = null;
        renderChecklists();
        toast(tr("Изменения сброшены"));
        break;
      case "activate-checklist":
        await api("/ui-api/checklists/activate", "POST", {
          id: S.checklist.id,
          version: S.checklist.version,
        });
        await refreshData();
        renderChecklists();
        toast(tr("Версия выбрана для новых оценок"));
        break;
      case "add-criterion": {
        if (S.draft.criteria.length >= 50) {
          toast(tr("Максимум 50 критериев"), true);
          break;
        }
        let n = 1;
        while (S.draft.criteria.some((c) => c.id === "c" + n)) n++;
        S.draft.criteria.push({
          id: "c" + n,
          title: tr("Новый критерий"),
          section: tr("Дополнительные критерии"),
          kind: "binary",
          weight: "5",
          max_score: "1",
          rule: "",
          options: [
            {
              value: "yes",
              raw_score: "1",
              description: tr("Требование выполнено"),
            },
            {
              value: "no",
              raw_score: "0",
              description: tr("Требование не выполнено"),
            },
          ],
          na_conditions: [],
          channel_rules: {},
          requires_company_knowledge: false,
          violation_value: null,
        });
        S.dirty = true;
        S.justAdded = true;
        renderEditorCriteria();
        $$(".edit-criterion").at(-1).setAttribute("open", "");
        $$(".edit-criterion")
          .at(-1)
          .scrollIntoView({ behavior: "smooth", block: "start" });
        break;
      }
      case "remove-criterion":
        S.draft.criteria.splice(Number(b.dataset.ci), 1);
        S.dirty = true;
        renderEditorCriteria();
        break;
      case "add-option": {
        const c = S.draft.criteria[Number(b.dataset.ci)],
          v = Math.max(...c.options.map((o) => Number(o.raw_score))) + 5;
        c.options.push({
          value: String(v),
          raw_score: String(v),
          description: "",
        });
        c.max_score = String(v);
        S.dirty = true;
        renderEditorCriteria();
        break;
      }
      case "remove-option": {
        const c = S.draft.criteria[Number(b.dataset.ci)];
        c.options.splice(Number(b.dataset.oi), 1);
        c.max_score = String(
          Math.max(...c.options.map((o) => Number(o.raw_score))),
        );
        S.dirty = true;
        renderEditorCriteria();
        break;
      }
      case "import":
        importModal();
        break;
      case "export":
        exportModal(
          S.page === "dialogues"
            ? undefined
            : S.data.conversations.map((r) => r.id),
        );
        break;
      case "detail-export":
        exportModal([S.detail.dialogue.conversation_id]);
        break;
      case "run-detail":
        await runDialogues([S.detail.dialogue.conversation_id]);
        break;
      case "run-selected":
        await runDialogues([...S.selected]);
        break;
      case "model-info":
        await modelInfo();
        break;
      case "jobs":
        S.data.jobs = await api("/ui-api/jobs");
        jobsModal();
        break;
      case "reweight": {
        const c = activeChecklist();
        const result = await api("/ui-api/reweight", "POST", {
          evaluation_id: S.detail.result.evaluation_id,
          checklist_id: c.id,
          checklist_version: c.version,
        });
        await refreshData();
        history.replaceState(
          null,
          "",
          conversationHref(
            result.conversation_id,
            result.evaluation_id,
            S.inReview,
          ),
        );
        await reloadDetail();
        toast(
          tr("Веса пересчитаны. Новый итог: ") +
            num(result.scoring.total_score),
        );
        break;
      }
      case "retry-load":
        await boot();
        break;
    }
  } catch (e) {
    toast(e.message, true);
  }
});

document.addEventListener("input", (event) => {
  const e = event.target;
  if (e.id === "dialogue-search") {
    S.q = e.value;
    S.offset = 0;
    renderTable();
  }
  if (e.id === "transcript-search") {
    S.transcriptSearch = e.value;
    renderTranscript();
    const found = $(".message.search-match");
    if (found) found.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  if (e.dataset.checklistField) {
    S.draft[e.dataset.checklistField] = e.value;
    S.dirty = true;
    updateDraftSummary();
  }
  if (
    e.dataset.ci !== undefined &&
    e.tagName !== "SELECT" &&
    e.type !== "checkbox"
  ) {
    const c = S.draft.criteria[Number(e.dataset.ci)];
    if (e.dataset.option !== undefined) {
      const o = c.options[Number(e.dataset.option)];
      o[e.dataset.optionField] = e.value;
      if (e.dataset.optionField === "raw_score") {
        if (c.kind === "scale") o.value = e.value;
        c.max_score = String(
          Math.max(...c.options.map((x) => Number(x.raw_score))),
        );
      }
    } else if (e.dataset.na !== undefined)
      c.na_conditions[Number(e.dataset.na)].description = e.value;
    else if (e.dataset.field === "max_observed_facts") {
      if (e.value === "") delete c.max_observed_facts;
      else c.max_observed_facts = Number(e.value);
    } else if (e.dataset.field) c[e.dataset.field] = e.value;
    S.dirty = true;
    updateDraftSummary();
    if (e.dataset.field === "title")
      $(`[data-edit-title="${e.dataset.ci}"]`).textContent = e.value;
  }
});
document.addEventListener("change", async (event) => {
  const e = event.target;
  try {
    if (e.id === "ui-language") {
      changeInterfaceLanguage(e.value);
      return;
    }
    if (e.id === "compare-before" || e.id === "compare-after") {
      if (!S.compare) return;
      S.compare[e.id === "compare-before" ? "before" : "after"] = e.value;
      await refreshChecklistComparison();
      return;
    }
    if (e.id === "compare-unchanged") {
      S.compare.showUnchanged = e.checked;
      renderChecklistComparison();
      return;
    }
    if (e.id === "review-comparison-scope") {
      S.reviewComparison.appealId = e.value || null;
      await refreshReviewComparison();
      return;
    }
    if (e.id === "review-comparison-unchanged") {
      S.reviewComparison.showUnchanged = e.checked;
      renderReviewComparison();
      return;
    }
    if (e.id === "role") {
      S.role = e.value;
      try {
        localStorage.setItem("cqa-role", S.role);
      } catch {
        /* Continue without persistence. */
      }
      updateChrome();
      if (S.page === "checklists") renderChecklists();
    }
    if (e.id === "language-filter") {
      S.language = e.value;
      S.offset = 0;
      renderTable();
    }
    if (e.id === "channel-filter") {
      S.channel = e.value;
      S.offset = 0;
      renderTable();
    }
    if (e.dataset.select) {
      e.checked
        ? S.selected.add(e.dataset.select)
        : S.selected.delete(e.dataset.select);
      renderTable();
    }
    if (e.id === "select-page") {
      filtered()
        .slice(S.offset * 12, S.offset * 12 + 12)
        .forEach((r) =>
          e.checked ? S.selected.add(r.id) : S.selected.delete(r.id),
        );
      renderTable();
    }
    if (e.id === "context-toggle") {
      S.showContext = e.checked;
      renderTranscript();
    }
    if (e.id === "evaluation-version") {
      const id = S.detail.dialogue.conversation_id;
      S.detail = await api(
        `/ui-api/conversations/${encodeURIComponent(id)}?evaluation_id=${encodeURIComponent(e.value)}`,
      );
      history.replaceState(null, "", conversationHref(id, e.value, S.inReview));
      renderDetail();
    }
    if (e.id === "resolve-answer") {
      const el = $("#resolve-na-field");
      if (el) el.hidden = e.value !== "na";
    }
    if (e.id === "import-file") await importFile(e.files[0]);
    if (
      e.dataset.ci !== undefined &&
      (e.tagName === "SELECT" || e.type === "checkbox")
    ) {
      const c = S.draft.criteria[Number(e.dataset.ci)];
      if (e.dataset.field === "kind") {
        c.kind = e.value;
        c.max_score = c.kind === "scale" ? "10" : "1";
        c.weight = c.kind === "flag" ? "0" : c.weight === "0" ? "5" : c.weight;
        c.violation_value = c.kind === "flag" ? "yes" : null;
        delete c.flag_evidence_mode;
        c.options =
          c.kind === "scale"
            ? [
                {
                  value: "0",
                  raw_score: "0",
                  description: tr("Требование не выполнено"),
                },
                {
                  value: "10",
                  raw_score: "10",
                  description: tr("Требование выполнено полностью"),
                },
              ]
            : [
                {
                  value: "yes",
                  raw_score: "1",
                  description:
                    c.kind === "flag"
                      ? tr("Нарушение обнаружено")
                      : tr("Требование выполнено"),
                },
                {
                  value: "no",
                  raw_score: "0",
                  description:
                    c.kind === "flag"
                      ? tr("Нарушение не обнаружено")
                      : tr("Требование не выполнено"),
                },
              ];
      } else if (e.dataset.field === "allow_na")
        c.na_conditions = e.checked
          ? [{ id: "not_applicable", description: "" }]
          : [];
      else {
        c[e.dataset.field] = e.checked;
        if (e.dataset.field === "requires_company_knowledge" && !e.checked) delete c.max_observed_facts;
      }
      S.dirty = true;
      renderEditorCriteria();
    }
  } catch (error) {
    toast(error.message, true);
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (
    ![
      "appeal-form",
      "resolution-form",
      "checklist-form",
      "import-form",
      "export-form",
      "run-form",
    ].includes(form.id)
  )
    return;
  event.preventDefault();
  const button = $('[type="submit"]', form),
    fd = new FormData(form);
  if (button) button.disabled = true;
  try {
    if (form.id === "appeal-form") {
      await api("/ui-api/appeals", "POST", {
        evaluation_id: fd.get("evaluation_id"),
        criterion_id: fd.get("criterion_id"),
        comment: fd.get("comment"),
        actor: S.role === "operator" ? tr("Оператор") : tr("Проверяющий"),
      });
      closeModal();
      await refreshData();
      await reloadDetail();
      toast(tr("Апелляция отправлена. Исходная оценка сохранена."));
    }
    if (form.id === "resolution-form") {
      await api(
        "/ui-api/appeals/" +
          encodeURIComponent(fd.get("appeal_id")) +
          "/resolve",
        "POST",
        {
          answer: fd.get("answer"),
          na_condition_id:
            fd.get("answer") === "na" ? fd.get("na_condition_id") : null,
          reason: fd.get("reason"),
          role: "reviewer",
          reviewer: tr("Проверяющий"),
        },
      );
      closeModal();
      await refreshData();
      if (S.detail) await reloadDetail();
      else renderPage();
      toast(tr("Решение сохранено. Итоговый балл пересчитан."));
      await openReviewComparison(
        S.resolving.appeal.evaluation_id,
        S.resolving.appeal.id,
      );
    }
    if (form.id === "checklist-form") {
      if (S.role !== "reviewer")
        throw new Error(tr("Переключитесь в роль проверяющего"));
      const saved = await api("/ui-api/checklists", "POST", S.draft);
      await refreshData();
      S.checklist = saved;
      S.draft = null;
      renderChecklists();
      toast(
        tr("Сохранена версия ") +
          saved.version +
          tr(". Она выбрана для новых оценок."),
      );
    }
    if (form.id === "import-form") {
      const pasted = $("#import-json").value.trim();
      if (pasted && !inspectImport(pasted, tr("Вставленный JSON"))) return;
      if (!S.importPayload)
        throw new Error(tr("Выберите файл или вставьте JSON"));
      const { data, ids } = S.importPayload;
      const result = await api("/ui-api/import", "POST", data);
      closeModal();
      try {
        await refreshData();
      } catch {
        toast(tr("Диалоги сохранены. Обновите страницу, чтобы открыть их."), true);
        return;
      }
      S.importedIds = new Set(result.conversation_ids ?? ids);
      S.selected.clear();
      S.filter = "file";
      S.language = S.channel = "all";
      S.q = "";
      S.offset = 0;
      const firstId = result.added_ids?.[0] ?? ids[0];
      const target = conversationHref(firstId);
      if (location.hash === target) await route();
      else location.hash = target;
      toast(result.added_ids
        ? msg`Добавлено: ${result.added_ids.length}. Уже было: ${result.imported - result.added_ids.length}.`
        : msg`Диалогов в файле: ${ids.length}.`);
    }
    if (form.id === "export-form") {
      const body = {
        conversation_ids: S.exportIds,
        evaluation_ids: S.exportEvaluations,
        format: fd.get("format"),
        dataset: fd.get("dataset"),
        team_name: fd.get("team_name"),
      };
      const result = await api("/ui-api/export", "POST", body);
      localStorage.setItem("cqa-team", body.team_name);
      download(
        result,
        body.format === "submission"
          ? "results-" + body.dataset + ".json"
          : "cqa-review-report.json",
      );
      closeModal();
      toast(tr("JSON подготовлен и передан для скачивания"));
    }
    if (form.id === "run-form") {
      const c = S.data.checklists[Number(fd.get("checklist"))];
      const result = await api("/ui-api/jobs", "POST", {
        conversation_ids: S.runIds,
        checklist_id: c.id,
        checklist_version: c.version,
      });
      closeModal();
      await refreshData();
      if (S.detail) renderDetail();
      else renderPage();
      toast(
        tr("В очереди ") +
          result.jobs.length +
          tr(" диалогов. Можно продолжить работу."),
      );
    }
  } catch (error) {
    if (form.id === "checklist-form") {
      const el = $("#checklist-error");
      el.hidden = false;
      el.className = "form-error";
      el.textContent = error.message;
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else modalError(error.message);
  } finally {
    if (button) button.disabled = false;
  }
});
document.addEventListener("dragover", (e) => {
  if (e.target.closest("#dropzone")) {
    e.preventDefault();
    $("#dropzone").classList.add("drag");
  }
});
document.addEventListener("dragleave", (e) => {
  if (e.target.closest("#dropzone")) $("#dropzone").classList.remove("drag");
});
document.addEventListener("drop", (e) => {
  if (e.target.closest("#dropzone")) {
    e.preventDefault();
    $("#dropzone").classList.remove("drag");
    importFile(e.dataTransfer.files[0]);
  }
});
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (S.page !== "dialogues" || S.detail) {
      location.hash = "/dialogues";
      setTimeout(() => $("#dialogue-search")?.focus(), 100);
    } else $("#dialogue-search")?.focus();
  }
});
$("#modal").addEventListener("close", () => {
  S.compare = null;
  S.reviewComparison = null;
  previousFocus?.focus();
});
$("#modal").addEventListener("click", (e) => {
  if (e.target === $("#modal")) {
    const r = e.target.getBoundingClientRect();
    if (
      e.clientX < r.left ||
      e.clientX > r.right ||
      e.clientY < r.top ||
      e.clientY > r.bottom
    )
      closeModal();
  }
});
document.addEventListener(
  "invalid",
  (event) => {
    const section = event.target.closest(".edit-criterion");
    if (section) section.open = true;
  },
  true,
);
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (event) => {
  if (S.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});
async function poll() {
  if (!S.data) return;
  try {
    const jobs = await api("/ui-api/jobs");
    const before = new Map(S.data.jobs.map((j) => [j.id, j.status]));
    const changed = jobs.some((j) => before.get(j.id) !== j.status);
    S.data.jobs = jobs;
    if (changed) {
      await refreshData();
      if (S.detail) await reloadDetail();
      else if (!S.dirty && !$("#modal").open) renderPage();
      const completed = jobs.filter(
        (j) =>
          before.get(j.id) &&
          before.get(j.id) !== j.status &&
          ["completed", "failed"].includes(j.status),
      );
      completed.forEach((j) =>
        toast(
          j.status === "completed"
            ? msg`${j.conversation_id}: оценка готова`
            : msg`${j.conversation_id}: анализ завершился ошибкой`,
          j.status === "failed",
        ),
      );
    }
    updateChrome();
  } catch {
    /* Foreground actions report network failures; background polling never replaces user work. */
  }
}
async function boot() {
  try {
    const legacyId = new URLSearchParams(location.search).get("conversation");
    if (!location.hash && legacyId) history.replaceState(null, "", location.pathname + conversationHref(legacyId));
    shell();
    $("#main").innerHTML = loading();
    await refreshData();
    await route();
    api("/ui-api/model")
      .then((m) => {
        S.model = m;
        updateChrome();
      })
      .catch(() => {});
    if (!S.poll) S.poll = setInterval(poll, 5000);
  } catch (e) {
    $("#main").innerHTML = empty(
      tr("Не удалось открыть пространство"),
      e.message,
      "alert",
      tr("Повторить"),
      "retry-load",
    );
  }
}
boot();
