/* tests/test_glossary_js.mjs — Node tests for indicator-glossary.js pure functions.
 * Run: node tests/test_glossary_js.mjs (Node 18+; no deps). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const Glossary = require("../site/indicator-glossary.js");
const data = JSON.parse(readFileSync(new URL("../site/data/indicator_glossary.json", import.meta.url), "utf-8"));
const byId = Object.fromEntries(data.terms.map((t) => [t.id, t]));

test("glossary JSON loads and every required term exists", () => {
  const required = ["cpi", "core-cpi", "ppi", "pce", "core-pce", "gdp", "pmi", "nfp",
    "unemployment", "initial-claims", "fomc", "fed-funds-rate", "treasury-10y",
    "treasury-2y", "yield-curve", "real-rate", "bp", "vix", "dxy", "credit-spread",
    "liquidity", "risk-appetite", "market-breadth", "pe", "pb", "eps", "macd", "rsi", "atr"];
  for (const id of required) assert.ok(byId[id], `missing ${id}`);
});

test("acceptance 1: CPI popover shows name + explanation + detail button", () => {
  const h = Glossary.popoverHTML(byId.cpi);
  assert.match(h, /消费者价格指数/);
  assert.match(h, /Consumer Price Index/);
  assert.match(h, /通俗|衡量/);
  assert.match(h, /为什么市场关注/);
  assert.match(h, /data-glossary-detail="cpi"/);
});

test("acceptance 2: PPI differs from CPI in definition and transmission", () => {
  const cpi = Glossary.detailHTML(byId.cpi, "explain");
  const ppi = Glossary.detailHTML(byId.ppi, "explain");
  assert.notEqual(byId.cpi.definition, byId.ppi.definition);
  assert.match(ppi, /生产者/);
  assert.match(cpi, /居民消费/);
  const ppiImpact = Glossary.tabBodyHTML(byId.ppi, "impact");
  assert.match(ppiImpact, /PPI|成本/);
});

test("acceptance 3: VIX says expected volatility, not a drop forecast", () => {
  const h = Glossary.popoverHTML(byId.vix);
  assert.match(h, /预期波动率/);
  const d = Glossary.detailHTML(byId.vix, "explain");
  assert.match(d, /不是确定的跌幅预测/);
});

test("acceptance 4: FOMC distinguishes decision from market expectation", () => {
  const d = Glossary.detailHTML(byId.fomc, "trading");
  assert.match(d, /决议本身.*市场预期/);
  assert.match(d, /符合预期/);
});

test("acceptance 5: detail panel has three tabs, switching keeps panel", () => {
  for (const tab of ["explain", "impact", "trading"]) {
    const h = Glossary.detailHTML(byId.cpi, tab);
    assert.match(h, /通俗解释/);
    assert.match(h, /市场影响/);
    assert.match(h, /交易应用/);
    assert.match(h, new RegExp(`data-glossary-tab="${tab}"`));
  }
  const impact = Glossary.tabBodyHTML(byId.cpi, "impact");
  assert.match(impact, /高于预期/);
  assert.match(impact, /低于预期/);
  assert.match(impact, /美股/);
});

test("acceptance 6+7: canvas link present when node exists, degrade text when not", () => {
  const cpiTrading = Glossary.tabBodyHTML(byId.cpi, "trading");
  assert.match(cpiTrading, /data-glossary-canvas="cpi"/);
  const cnTrading = Glossary.tabBodyHTML(byId["cpi-cn"], "trading");
  assert.match(cnTrading, /无对应节点/);
  assert.doesNotMatch(cnTrading, /data-glossary-canvas/);
});

test("related indicators are clickable term links", () => {
  const h = Glossary.detailHTML(byId.cpi, "impact");
  assert.match(h, /data-indicator="core-cpi"/);
});

test("fallback terms exist for offline use", () => {
  assert.ok(Glossary.FALLBACK_TERMS.length >= 3);
  const ids = Glossary.FALLBACK_TERMS.map((t) => t.id);
  for (const id of ["cpi", "vix", "fomc"]) assert.ok(ids.includes(id));
});
