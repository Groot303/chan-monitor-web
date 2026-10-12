#!/usr/bin/env python3
"""Run US strategy lab daily backtest and write reports under out/ + site/data/strategy/."""
from __future__ import annotations
import argparse, json, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quant.config import StrategyConfig
from quant.adapters.yahoo import YahooCsvAdapter
from quant.adapters.ibkr import IbkrAdapterStub
from quant.backtest import DailyBacktester, load_universe


def to_md(result: dict) -> str:
    p = result.get("performance") or {}
    lines = [
        "# 美股策略研究回测报告",
        "",
        f"- 版本: `{result.get('version')}`",
        f"- 生成: {datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()}Z",
        f"- 成交规则: {result.get('fill_rule')}",
        f"- IBKR: {IbkrAdapterStub().health()['status']}（第一版禁止真实下单）",
        "",
        "> 历史研究结果，**不能**外推未来收益。评分≠上涨概率。不构成投资建议。",
        "",
        "## 绩效摘要",
        "",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| 总收益率 | {_pct(p.get('total_return'))} |",
        f"| CAGR | {_pct(p.get('cagr'))} |",
        f"| 最大回撤 | {_pct(p.get('max_drawdown'))} |",
        f"| Sharpe | {_num(p.get('sharpe'))} |",
        f"| Sortino | {_num(p.get('sortino'))} |",
        f"| 交易次数(已平仓) | {p.get('trades')} |",
        f"| 胜率 | {_pct(p.get('win_rate'))} |",
        f"| 平均盈利 | {_num(p.get('avg_win'))} |",
        f"| 平均亏损 | {_num(p.get('avg_loss'))} |",
        f"| 平均盈亏比 | {_num(p.get('avg_rr'))} |",
        f"| 期望收益/笔 | {_num(p.get('expectancy'))} |",
        f"| Profit Factor | {_num(p.get('profit_factor'))} |",
        f"| 平均持仓天数 | {_num(p.get('avg_hold_days'))} |",
        f"| 期末权益 | {_num(p.get('final_equity'))} |",
        "",
        "## 基准（同期买入持有）",
        "",
    ]
    for k, v in (p.get("benchmarks") or {}).items():
        lines.append(f"- {k}: {_pct(v)}")
    lines += ["", "## 市场状态（最新）", "", f"```json\n{json.dumps(result.get('regime_latest'), ensure_ascii=False, indent=2)}\n```", ""]
    lines += ["## 事件（回撤暂停等）", ""]
    ev = result.get("events") or []
    if not ev:
        lines.append("（无）")
    else:
        for e in ev[:30]:
            lines.append(f"- {e}")
    lines += ["", "## 已平仓交易（最多 40 笔）", ""]
    closed = [t for t in result.get("trades", []) if t.get("status") == "closed"][:40]
    if not closed:
        lines.append("无已平仓交易（样本不足或未触发）。")
    else:
        lines.append("| 标的 | 策略 | 信号日 | 入场 | 出场 | 原因 | PnL |")
        lines.append("|---|---|---|---|---|---|---|")
        for t in closed:
            lines.append(
                f"| {t['symbol']} | {t['strategy']} | {t.get('signal_date')} | "
                f"{t.get('entry_price'):.2f} | {t.get('exit_price'):.2f} | {t.get('exit_reason')} | {t.get('pnl'):.2f} |"
            )
    lines += ["", result.get("performance_note", ""), "", result.get("disclaimer", "")]
    return "\n".join(lines)


def _pct(x):
    if x is None:
        return "—"
    return f"{100*float(x):.2f}%"


def _num(x):
    if x is None:
        return "—"
    return f"{float(x):.4f}" if abs(float(x)) < 10 else f"{float(x):.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-07-01", help="回测起始日")
    ap.add_argument("--end", default=None)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    args = ap.parse_args()

    cfg = StrategyConfig()
    adapter = YahooCsvAdapter(allow_download=not args.no_download)
    data, benches, failures = load_universe(adapter, cfg.watchlist, cfg.benchmarks, args.start, args.end)

    bt = DailyBacktester(cfg)
    result = bt.run(data, benches, start=args.start, end=args.end)
    result["failures"] = failures
    result["generated"] = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    result["ibkr"] = IbkrAdapterStub().health()
    result["symbols_loaded"] = sorted(data.keys())
    result["benchmarks_loaded"] = sorted(benches.keys())

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, "strategy_backtest.json")
    md_path = os.path.join(args.out, "strategy_backtest.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_md(result))

    # publish slim payload for static site
    site_dir = os.path.join(ROOT, "site", "data", "strategy")
    os.makedirs(site_dir, exist_ok=True)
    slim = {
        "generated": result["generated"],
        "version": result.get("version"),
        "fill_rule": result.get("fill_rule"),
        "disclaimer": result.get("disclaimer"),
        "performance_note": result.get("performance_note"),
        "performance": result.get("performance"),
        "regime_latest": result.get("regime_latest"),
        "equity_curve": result.get("equity_curve"),
        "trades": result.get("trades"),
        "events": result.get("events"),
        "signals_sample": result.get("signals_sample"),
        "failures": failures,
        "symbols_loaded": result.get("symbols_loaded"),
        "benchmarks_loaded": result.get("benchmarks_loaded"),
        "ibkr": result.get("ibkr"),
        "watchlist": cfg.watchlist,
        "config_summary": {
            "score_entry_min": cfg.score_entry_min,
            "risk_per_trade": cfg.risk.risk_per_trade,
            "max_position_pct": cfg.risk.max_position_pct,
            "max_positions": cfg.risk.max_positions,
            "max_drawdown": cfg.risk.max_drawdown,
            "initial_cash": cfg.risk.initial_cash,
            "start": args.start,
            "end": args.end,
        },
    }
    with open(os.path.join(site_dir, "backtest.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=2, default=str)

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"symbols={result.get('symbols_loaded')} failures={failures}")
    perf = result.get("performance") or {}
    print(f"return={perf.get('total_return')} trades={perf.get('trades')} maxdd={perf.get('max_drawdown')}")
    return 0 if data else 1


if __name__ == "__main__":
    raise SystemExit(main())
