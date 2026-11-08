"use strict";

// Localize UI literals only. Interpolated dialogue text, evidence, comments and
// editable rubric values are opaque slots and never pass through translation.
window.CqaI18n = (() => {
  const languages = { ru: "ru-RU", kk: "kk-KZ", en: "en-GB" };
  const messages = window.CQA_MESSAGES || {};
  const missing = new Set();
  const slot = /\uE000(\d+)\uE001/g;
  const stored = (key) => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  };
  const remember = (key, value) => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* Preferences are optional. */
    }
  };
  let language = Object.hasOwn(languages, stored("cqa-ui-language"))
    ? stored("cqa-ui-language")
    : "ru";
  let theme = stored("cqa-theme") === "dark" ? "dark" : "light";

  function translate(raw, ...values) {
    const source = String(raw ?? "");
    const key = source.trim().replace(/\s+/g, " ");
    if (!key) return source;
    const entry = messages[key];
    const translated = language === "ru" ? key : (entry?.[language] ?? key);
    if (language !== "ru" && /[А-Яа-яЁё]/.test(key) && !entry?.[language])
      missing.add(key);
    const text = translated.replace(/\{(\d+)\}/g, (match, index) =>
      index < values.length ? String(values[index]) : match,
    );
    return (
      (source.match(/^\s*/)?.[0] || "") +
      text +
      (source.match(/\s*$/)?.[0] || "")
    );
  }

  function phrase(source) {
    const tokens = [];
    const key = source.replace(slot, (token) => `{${tokens.push(token) - 1}}`);
    return translate(key, ...tokens);
  }
  function prepare(strings, values) {
    return typeof strings === "string"
      ? strings
      : strings.reduce(
          (s, part, index) =>
            s + part + (index < values.length ? `\uE000${index}\uE001` : ""),
          "",
        );
  }
  function fill(source, values) {
    return source.replace(slot, (_, index) => String(values[index] ?? ""));
  }
  function text(strings, ...values) {
    return fill(phrase(prepare(strings, values)), values);
  }
  function html(strings, ...values) {
    let source = prepare(strings, values);
    if (language !== "ru") {
      // Do not parse the interpolated HTML or inspect the rendered DOM: a
      // customer's message can equal a UI label and still must remain verbatim.
      source = source.replace(
        /(^|>)([^<]*)(?=<|$)/g,
        (_, prefix, content) => prefix + phrase(content),
      );
      source = source.replace(
        /\b(aria-label|title|placeholder|alt)=("([^"]*)"|'([^']*)')/g,
        (_, attribute, quoted, double, single) => {
          const translated = phrase(double ?? single);
          return `${attribute}="${translated.replace(/"/g, "&quot;")}"`;
        },
      );
    }
    return fill(source, values);
  }
  function setLanguage(value) {
    if (!Object.hasOwn(languages, value)) return;
    language = value;
    document.documentElement.lang = value;
    remember("cqa-ui-language", value);
  }
  function setTheme(value) {
    if (!["light", "dark"].includes(value)) return;
    theme = value;
    document.documentElement.dataset.theme = value;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", value === "dark" ? "#0e1c25" : "#f4f5f7");
    remember("cqa-theme", value);
  }
  setLanguage(language);
  setTheme(theme);
  return {
    translate,
    text,
    html,
    setLanguage,
    setTheme,
    missing,
    get language() {
      return language;
    },
    get locale() {
      return languages[language];
    },
    get theme() {
      return theme;
    },
  };
})();
