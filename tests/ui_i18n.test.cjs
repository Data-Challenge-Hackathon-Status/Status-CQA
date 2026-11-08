const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function runtime(storage = new Map(), unavailable = false) {
  const document = {
    documentElement: { lang: "ru", dataset: {} },
    querySelector: () => ({ setAttribute() {} }),
  };
  const context = vm.createContext({
    window: {},
    document,
    localStorage: {
      getItem(key) {
        if (unavailable) throw new Error("Blocked storage");
        return storage.get(key);
      },
      setItem(key, value) {
        if (unavailable) throw new Error("Blocked storage");
        storage.set(key, value);
      },
    },
  });
  for (const name of ["i18n-catalog.js", "i18n.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../cqa/web_assets", name), "utf8"),
      context,
    );
  }
  return {
    i18n: context.window.CqaI18n,
    catalog: context.window.CQA_MESSAGES,
    document,
    storage,
  };
}

test("all translated messages preserve their substitution slots", () => {
  const { catalog } = runtime();
  const slots = (text) => (text.match(/\{\d+\}/g) || []).sort();
  for (const [source, translations] of Object.entries(catalog)) {
    for (const language of ["kk", "en"]) {
      assert.ok(translations[language]?.trim(), `${language}: ${source}`);
      assert.deepEqual(
        slots(translations[language]),
        slots(source),
        `${language}: ${source}`,
      );
    }
  }
});

test("customer text identical to a UI label remains verbatim in all languages", () => {
  const { i18n } = runtime();
  const customerText = "Да";
  for (const [lang, label] of [
    ["ru", "Да"],
    ["kk", "Иә"],
    ["en", "Yes"],
  ]) {
    i18n.setLanguage(lang);
    assert.equal(
      i18n.html`<b>Да</b><p>${customerText}</p>`,
      `<b>${label}</b><p>Да</p>`,
    );
  }
});

test("editable rubric content and already escaped evidence are opaque", () => {
  const { i18n } = runtime();
  i18n.setLanguage("en");
  const evidence = "&lt;script&gt;Да&lt;/script&gt; {0} $&";
  assert.equal(
    i18n.html`<label>Да</label><textarea>${evidence}</textarea>`,
    `<label>Yes</label><textarea>${evidence}</textarea>`,
  );
  assert.equal(
    i18n.html`<input value="${"Нет"}" aria-label="Название">`,
    '<input value="Нет" aria-label="Name">',
  );
});

test("conditional HTML attributes and nested localized markup survive rendering", () => {
  const { i18n } = runtime();
  i18n.setLanguage("en");
  const button = i18n.html`<button ${"disabled"} aria-label="Закрыть">Отмена</button>`;
  assert.equal(button, '<button disabled aria-label="Close">Cancel</button>');
  assert.equal(
    i18n.html`<section>${button}<b>Да</b></section>`,
    `<section>${button}<b>Yes</b></section>`,
  );
});

test("Kazakh can reorder substitutions without changing values", () => {
  const { i18n } = runtime();
  i18n.setLanguage("kk");
  assert.equal(
    i18n.text`${1}–${12} из ${65} диалогов${""}`,
    "65 диалогтың 1–12 аралығы",
  );
  assert.equal(i18n.translate(" "), " ");
});

test("preferences survive a fresh page and update language and color scheme", () => {
  const first = runtime();
  first.i18n.setLanguage("kk");
  first.i18n.setTheme("dark");
  const fresh = runtime(first.storage);
  assert.equal(fresh.i18n.language, "kk");
  assert.equal(fresh.i18n.locale, "kk-KZ");
  assert.equal(fresh.document.documentElement.lang, "kk");
  assert.equal(fresh.document.documentElement.dataset.theme, "dark");
  fresh.i18n.setLanguage("invalid");
  fresh.i18n.setTheme("invalid");
  assert.equal(fresh.i18n.language, "kk");
  assert.equal(fresh.i18n.theme, "dark");
});

test("unavailable storage does not prevent the interface from working", () => {
  const { i18n } = runtime(new Map(), true);
  i18n.setLanguage("en");
  i18n.setTheme("dark");
  assert.equal(i18n.translate("Диалоги"), "Dialogues");
  assert.equal(i18n.theme, "dark");
});
