import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const readJson = (file) => JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
const catalogs = Object.fromEntries(["en", "ru", "zh-CN"].map(locale => [locale, readJson(path.join(root, "src/locales", locale + ".json"))]));
const names = value => [...value.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match => match[1]).sort();
const keys = Object.keys(catalogs.en).sort();
for (const locale of ["ru", "zh-CN"]) {
  const missing = keys.filter(key => !Object.hasOwn(catalogs[locale], key));
  const extra = Object.keys(catalogs[locale]).filter(key => !Object.hasOwn(catalogs.en, key));
  assert.ok(!missing.length && !extra.length, `${locale}: missing ${JSON.stringify(missing)}, extra ${JSON.stringify(extra)}`);
  for (const key of keys) {
    const value = catalogs[locale][key];
    assert.equal(typeof value, "string", `${locale}: ${key} is not text`);
    assert.ok(value.trim(), `${locale}: ${key} is empty`);
    assert.deepEqual(names(value), names(key), `${locale}: ${key} lost interpolation placeholders`);
  }
}

// A new hard-coded JSX label or a missing literal key should fail verification.
for (const file of ["App.tsx", "LanguageSwitcher.tsx", "i18n.ts"]) {
  const source = ts.createSourceFile(file, fs.readFileSync(path.join(root, "src", file), "utf8"), ts.ScriptTarget.Latest, true, file.endsWith("tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const visit = node => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && ["formatNumber", "formatDate"].includes(node.expression.text)) {
      for (let parent = node.parent; parent && !ts.isJsxElement(parent) && !ts.isStatement(parent); parent = parent.parent) {
        if (ts.isJsxAttribute(parent)) {
          assert.ok(!["value", "defaultValue"].includes(parent.name.getText(source)), `Locale formatting must not change form values in ${file}`);
        }
      }
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "t" && node.arguments[0] && ts.isStringLiteralLike(node.arguments[0])) {
      assert.ok(Object.hasOwn(catalogs.en, node.arguments[0].text), `Missing key in ${file}: ${node.arguments[0].text}`);
      assert.ok(!/^(?:\/|https?:|cfg-|computeforgood\.)/.test(node.arguments[0].text), `Protocol value was translated in ${file}: ${node.arguments[0].text}`);
      for (let parent = node.parent; parent && !ts.isJsxElement(parent) && !ts.isStatement(parent); parent = parent.parent) {
        if (ts.isJsxAttribute(parent)) {
          assert.ok(!["value", "to", "href", "name", "type", "className"].includes(parent.name.getText(source)), `Machine attribute was translated in ${file}: ${parent.name.getText(source)}`);
        }
        if (ts.isPropertyAssignment(parent)) {
          assert.ok(!["status", "decision", "risk", "required_model_tier"].includes(parent.name.getText(source)), `Protocol enum was translated in ${file}: ${parent.name.getText(source)}`);
        }
      }
    }
    if (ts.isJsxText(node) && /[A-Za-z]{2}/.test(node.text)) {
      const parent = node.parent;
      const tag = ts.isJsxElement(parent) ? parent.openingElement.tagName.getText(source) : "";
      const text = node.text.trim();
      assert.ok(["code", "pre"].includes(tag) || /^(Compute|ForGood|ComputeForGood|MCP|GitHub|PR|SHA)$/.test(text), `Untranslated JSX in ${file}: ${text}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
}

const require = createRequire(path.join(root, "src/i18n.ts"));
const compiled = ts.transpileModule(fs.readFileSync(path.join(root, "src/i18n.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;
function load({ saved = null, languages = ["en-US"], blocked = false } = {}) {
  const storage = new Map(saved ? [["cfg-language", saved]] : []);
  const events = {};
  const attributes = new Map();
  const document = {
    documentElement: { lang: "" }, title: "",
    querySelector: selector => ({ setAttribute: (name, value) => attributes.set(selector + name, value) }),
  };
  const window = {
    navigator: { languages, language: languages[0] },
    localStorage: {
      getItem: key => { if (blocked) throw Error("Storage blocked"); return storage.get(key) ?? null; },
      setItem: (key, value) => { if (blocked) throw Error("Storage blocked"); storage.set(key, value); },
    },
    addEventListener: (name, handler) => { events[name] = handler; },
  };
  const module = { exports: {} };
  vm.runInNewContext(compiled, { exports: module.exports, require, window, document, Intl, Date });
  return { api: module.exports, document, storage, events };
}
const browser = load({ saved: "ru", languages: ["zh-CN"] });
assert.equal(browser.api.getLocale(), "ru", "Saved preference should win");
assert.equal(browser.api.t("Language"), catalogs.ru.Language);
assert.equal(browser.document.documentElement.lang, "ru");
assert.equal(browser.api.t("Request failed ({status})", { status: 409 }), catalogs.ru["Request failed ({status})"].replace("{status}", "409"));
assert.equal(browser.api.t("Unknown repository content"), "Unknown repository content", "Unknown content remains unchanged");
browser.api.setLocale("zh-CN");
assert.equal(browser.storage.get("cfg-language"), "zh-CN");
assert.equal(browser.document.documentElement.lang, "zh-CN");
assert.equal(browser.api.t("Language"), catalogs["zh-CN"].Language);
assert.equal(browser.api.formatNumber(12345.6), new Intl.NumberFormat("zh-CN").format(12345.6));
assert.equal(browser.api.formatDate("2026-10-03T12:30:00Z"), new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date("2026-10-03T12:30:00Z")));
browser.events.storage({ key: "cfg-language", newValue: "en" });
assert.equal(browser.api.getLocale(), "en", "Other tabs update the selected language");
assert.equal(load({ saved: "unsupported", languages: ["fr-FR", "ru-RU"] }).api.getLocale(), "ru");
assert.equal(load({ languages: ["zh-TW"] }).api.getLocale(), "zh-CN");
const restricted = load({ blocked: true, languages: ["ru-RU"] });
restricted.api.setLocale("zh-CN");
assert.equal(restricted.api.getLocale(), "zh-CN", "Language switching survives blocked storage");
assert.equal(load({ languages: ["fr-FR"] }).api.getLocale(), "en", "Unsupported locale falls back to English");
console.log(`i18n verified: ${keys.length} keys in English, Russian and Simplified Chinese; interpolation, persistence, fallback, document language and Intl formatting passed.`);
