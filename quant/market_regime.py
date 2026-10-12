"""Market regime from QQQ/SPY — trend and volatility modeled separately."""
from __future__ import annotations
from typing import Dict, Any, Optional
import pandas as pd
from .indicators import enrich


def classify_row(row: pd.Series) -> Dict[str, Any]:
    """Classify a single already-enriched bar. Uses only that bar's fields."""
    needed = ["Close", "MA20", "MA50", "MA200", "ATR_PCT", "VOL20", "RET20", "RET60"]
    if any(pd.isna(row.get(k)) for k in needed):
        return {
            "trend": "数据不足",
            "volatility": "数据不足",
            "label": "数据不足或状态不明",
            "ret20": None,
            "ret60": None,
            "atr_pct": None,
            "vol20": None,
        }

    close, ma20, ma50, ma200 = row["Close"], row["MA20"], row["MA50"], row["MA200"]
    if close > ma50 > ma20 * 0.98 and ma50 > ma200:
        trend = "上升趋势"
    elif close < ma50 < ma20 * 1.02 and ma50 < ma200:
        trend = "下降趋势"
    else:
        trend = "震荡"

    atr_pct = float(row["ATR_PCT"])
    vol20 = float(row["VOL20"])
    # high vol if ATR% > 2.5% or annualized vol > 25%
    volatility = "高波动" if (atr_pct > 0.025 or vol20 > 0.25) else "正常波动"

    label = f"{trend} / {volatility}"
    return {
        "trend": trend,
        "volatility": volatility,
        "label": label,
        "ret20": float(row["RET20"]),
        "ret60": float(row["RET60"]),
        "atr_pct": atr_pct,
        "vol20": vol20,
        "close": float(close),
        "ma20": float(ma20),
        "ma50": float(ma50),
        "ma200": float(ma200),
    }


def regime_series(df: pd.DataFrame) -> pd.DataFrame:
    en = enrich(df)
    rows = [classify_row(en.iloc[i]) for i in range(len(en))]
    reg = pd.DataFrame(rows, index=en.index)
    return pd.concat([en, reg], axis=1)


def latest_regime(qqq: Optional[pd.DataFrame], spy: Optional[pd.DataFrame]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"qqq": None, "spy": None, "combined_trend": "数据不足或状态不明"}
    if qqq is not None and len(qqq) > 0:
        out["qqq"] = classify_row(enrich(qqq).iloc[-1])
    if spy is not None and len(spy) > 0:
        out["spy"] = classify_row(enrich(spy).iloc[-1])
    trends = []
    for k in ("qqq", "spy"):
        if out[k] and out[k]["trend"] not in ("数据不足",):
            trends.append(out[k]["trend"])
    if not trends:
        out["combined_trend"] = "数据不足或状态不明"
    elif all(t == "上升趋势" for t in trends):
        out["combined_trend"] = "上升趋势"
    elif all(t == "下降趋势" for t in trends):
        out["combined_trend"] = "下降趋势"
    else:
        out["combined_trend"] = "震荡或分歧"
    return out
