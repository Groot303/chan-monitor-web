#!/usr/bin/env python3
"""Turn chan-monitor output (out/signals.json + out/*_chan2.png) into site/data and site/img.
Usage: python3 scripts/build_data.py [SRC_OUT_DIR] [--market us|cn]   (default: out, us)

  us: reads out/signals.json        -> site/data/signals.json, site/img/,        site/data/charts/
  cn: reads out_cn/signals.json     -> site/data/signals_cn.json, site/img_cn/,  site/data/charts_cn/
"""
import argparse
import json, os, shutil, sys

ap = argparse.ArgumentParser()
ap.add_argument("src", nargs="?", default="out")
ap.add_argument("--market", default="us", choices=["us", "cn"])
ap.add_argument("--outdir", default=None, help="output base dir (default: site/)")
args = ap.parse_args()
src = args.src
market = args.market

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
from signal_safety import regime_decision
# API_MODE: output to API_DATA_DIR instead of site/
outbase = args.outdir or os.environ.get("API_DATA_DIR") or os.path.join(root, "site")
site = outbase
if market == "cn":
    data_name, img_dirname, charts_dirname = "signals_cn.json", "img_cn", "charts_cn"
else:
    data_name, img_dirname, charts_dirname = "signals.json", "img", "charts"
os.makedirs(os.path.join(site, "data"), exist_ok=True)
os.makedirs(os.path.join(site, img_dirname), exist_ok=True)
d = json.load(open(os.path.join(src, "signals.json")))
signals, symbols = [], {}
for sym, ent in d["symbols"].items():
    lv_info = {}
    for lv, x in ent["levels"].items():
        lv_info[lv] = {k: x[k] for k in ("bars", "first", "last", "last_close", "state", "last_segment")}
        signals.extend(x["signals"])
    img = f"{sym}_chan2.png"
    has = os.path.exists(os.path.join(src, img))
    if has:
        shutil.copyfile(os.path.join(src, img), os.path.join(site, img_dirname, img))
    symbols[sym] = {"image": f"{img_dirname}/{img}" if has else None, "levels": lv_info, "code": ent.get("code")}
signals.sort(key=lambda g: -g.get("score", 0))
out = {"generated": d["generated"], "market": d.get("market", market),
       "failures": d.get("failures", {}), "symbols": symbols, "signals": signals,
       "regime": d.get("regime", {}), "strategy_context": regime_decision(d.get("regime", {}))}
with open(os.path.join(site, "data", data_name), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"[{market}] wrote {len(signals)} signals, {len(symbols)} symbols -> data/{data_name}")

# Macro snapshot (US pipeline only): out/macro.json -> site/data/macro.json
if market == "us":
    # 原子发布，避免定时模拟读取写到一半的数据；缺失则明确失效旧证据。
    _strategy_path = os.path.join(site, "data", "strategy_source_us.json")
    _strategy_source = os.path.join(src, "strategy_source_us.json")
    _strategy_data = json.load(open(_strategy_source)) if os.path.exists(_strategy_source) else {"error": "source missing"}
    with open(_strategy_path + ".tmp", "w") as _f:
        json.dump(_strategy_data, _f)
    os.replace(_strategy_path + ".tmp", _strategy_path)
    try:
        _mp = os.path.join(src, "macro.json")
        if os.path.exists(_mp):
            shutil.copyfile(_mp, os.path.join(site, "data", "macro.json"))
            print("[us] macro -> data/macro.json")
        else:
            print(f"[us] macro.json missing in {src}, skipped")
    except Exception as _e:
        print(f"[us] macro copy skipped: {_e}")

# Optional: export interactive chart JSON for sample symbols when CSVs are present.
try:
    import importlib.util as _ilu
    _spec=_ilu.spec_from_file_location("export_chart", os.path.join(os.path.dirname(__file__), "export_chart.py"))
    _mod=_ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
    export_symbol=_mod.export_symbol
    import json as _json
    charts_dir = os.path.join(site, "data", charts_dirname)
    os.makedirs(charts_dir, exist_ok=True)
    data_dirs = [os.path.join(root, src), root, os.path.join(root, "..", "chan-monitor")]
    for _sym in sorted(d["symbols"].keys()):
        try:
            payload = export_symbol(_sym, data_dirs, tz="Asia/Shanghai" if market == "cn" else "America/New_York")
            with open(os.path.join(charts_dir, f"{_sym}.json"), "w", encoding="utf-8") as _f:
                _json.dump(payload, _f, ensure_ascii=False, separators=(",", ":"))
            print(f"[{market}] chart {_sym}: ok")
        except Exception as _e:
            print(f"[{market}] chart {_sym}: skip ({_e})")
except Exception as _e:
    print(f"[{market}] chart export skipped: {_e}")
