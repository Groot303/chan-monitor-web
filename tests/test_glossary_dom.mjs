/* tests/test_glossary_dom.mjs — DOM-stub smoke test for indicator-glossary.js wiring.
 * Verifies: single delegated listener, open/close cycle, Esc, no duplicate layers.
 * Run: node tests/test_glossary_dom.mjs */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

function makeEnv(viewportWidth) {
  const listeners = {};
  const children = [];
  function fakeEl(tag) {
    const el = {
      tagName: (tag || "div").toUpperCase(),
      className: "",
      style: {},
      dataset: {},
      children: [],
      parentNode: null,
      innerHTML: "",
      attributes: {},
      setAttribute(k, v) { this.attributes[k] = v; },
      getAttribute(k) { return this.attributes[k] ?? null; },
      appendChild(c) { c.parentNode = this; this.children.push(c); children.push(c); return c; },
      removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; },
      querySelector(sel) {
        if (sel === "[data-glossary-close]") return { focus() { el._focused = true; } };
        return null;
      },
      querySelectorAll() { return []; },
      closest(sel) { return sel === "[data-indicator]" ? el : null; },
      focus() { el._focused = true; },
      click() {},
      scrollIntoView() {},
      getBoundingClientRect() { return { left: 100, top: 100, bottom: 130, right: 200, width: 100, height: 30 }; },
    };
    Object.defineProperty(el, "offsetHeight", { value: 200 });
    return el;
  }
  const body = fakeEl("body");
  body.classList = { toggle() {}, add() {}, remove() {} };
  const document = {
    body,
    readyState: "complete",
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener(type, fn) {
      listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
    },
    createElement: fakeEl,
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  const window = { innerWidth: viewportWidth };
  const localStorage = { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = v; } };
  const sandbox = {
    document, window, localStorage,
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ terms: [] }) }),
    setTimeout, console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  const src = readFileSync(new URL("../site/indicator-glossary.js", import.meta.url), "utf-8");
  vm.runInContext(src, sandbox);
  return { sandbox, document, body, listeners, fakeEl };
}

function fireClick(env, target) {
  for (const fn of env.listeners.click || []) fn({ target });
}
function fireKey(env, key) {
  for (const fn of env.listeners.keydown || []) fn({ key });
}

test("clicking a term opens exactly one popover; second click replaces, not duplicates", async () => {
  const env = makeEnv(1200);
  const termEl = env.fakeEl("span");
  termEl.getAttribute = () => "cpi";
  termEl.closest = (sel) => (sel === "[data-indicator]" ? termEl : null);
  // Wait for the module's async glossary load (fallback path).
  await new Promise((r) => setTimeout(r, 50));
  fireClick(env, termEl);
  const pops1 = env.body.children.filter((c) => c.className === "gl-pop");
  assert.equal(pops1.length, 1, "one popover after first click");
  assert.match(pops1[0].innerHTML, /消费者价格指数/);
  fireClick(env, termEl);
  const pops2 = env.body.children.filter((c) => c.className === "gl-pop");
  assert.equal(pops2.length, 1, "still one popover after second click (replaced)");
});

test("Esc closes the popover and returns focus", async () => {
  const env = makeEnv(1200);
  const termEl = env.fakeEl("span");
  termEl.getAttribute = () => "vix";
  termEl.closest = (sel) => (sel === "[data-indicator]" ? termEl : null);
  await new Promise((r) => setTimeout(r, 50));
  fireClick(env, termEl);
  assert.equal(env.body.children.filter((c) => c.className === "gl-pop").length, 1);
  fireKey(env, "Escape");
  assert.equal(env.body.children.filter((c) => c.className === "gl-pop").length, 0);
  assert.equal(termEl._focused, true, "focus returns to trigger");
});

test("mobile width opens a bottom sheet, not a popover", async () => {
  const env = makeEnv(390); // iPhone width
  const termEl = env.fakeEl("span");
  termEl.getAttribute = () => "fomc";
  termEl.closest = (sel) => (sel === "[data-indicator]" ? termEl : null);
  await new Promise((r) => setTimeout(r, 50));
  fireClick(env, termEl);
  assert.equal(env.body.children.filter((c) => c.className === "gl-sheet").length, 1);
  assert.equal(env.body.children.filter((c) => c.className === "gl-pop").length, 0);
  assert.equal(env.body.children.filter((c) => c.className === "gl-backdrop").length, 1);
});

test("single delegated click listener (no per-term listeners)", async () => {
  const env = makeEnv(1200);
  assert.equal((env.listeners.click || []).length, 1, "exactly one document click listener");
  assert.equal((env.listeners.keydown || []).length, 1, "exactly one keydown listener");
});
