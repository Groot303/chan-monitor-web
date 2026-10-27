"""P0 additive contracts. No detector or score changes; no trading execution."""
import math


def unknown_regime(benchmark, error):
    # bear remains a boolean for old consumers; status/known are authoritative.
    return {"benchmark": benchmark, "bear": False, "status": "unknown", "known": False,
            "error": str(error)[:120]}


def measured_regime(benchmark, closes, *, bar_complete=None):
    try:
        values = [float(x) for x in closes]
    except (TypeError, ValueError):
        return unknown_regime(benchmark, "missing or invalid benchmark closes")
    if len(values) < 210 or not all(math.isfinite(x) and x > 0 for x in values):
        return unknown_regime(benchmark, "missing, invalid or insufficient benchmark closes")
    mean = sum(values[-200:]) / 200
    bear = values[-1] < mean
    return {"benchmark": benchmark, "bear": bear, "known": True,
            "status": "bear" if bear else "non_bear", "close": round(values[-1], 2),
            "sma200": round(mean, 2),
            "bar_completion": "complete" if bar_complete is True else "incomplete" if bar_complete is False else "unknown"}


def regime_state(regime):
    """Old bear=False cannot establish safety: errors/missing contract fail closed."""
    if not isinstance(regime, dict) or regime.get("error") or regime.get("known") is not True:
        return "unknown"
    status = regime.get("status")
    if status == "bear" and regime.get("bear") is True:
        return status
    if status == "non_bear" and regime.get("bear") is False:
        return status
    return "unknown"


def regime_decision(regime):
    state = regime_state(regime)
    if state == "non_bear" and regime.get("bar_completion") != "complete":
        state = "unknown"
    return {"regime_state": state, "new_long_environment":
            {"bear": "blocked", "unknown": "unknown", "non_bear": "permitted"}[state]}


def confirmation_contract(signal):
    edge = signal.get("kind") == "pivot_edge" or signal.get("type") in ("ZD_B", "ZG_S")
    return {"touch_confirmed": bool(signal.get("confirmed")) if edge else None,
            "structure_confirmed": None if edge else bool(signal.get("confirmed")),
            "entry_confirmed": None,
            "confirmation_scope": "edge_touch_in_snapshot" if edge else "segment_in_snapshot"}


def snapshot_contract(signal, index):
    """An index label is evidence of an extremum label, never of availability."""
    confirmation = confirmation_contract(signal)
    edge = confirmation["confirmation_scope"] == "edge_touch_in_snapshot"
    label = index[signal["idx"]].isoformat()
    return {**confirmation, "signal_bar_time": label,
            "bar_time_role": "touch" if edge else "extreme",
            "extreme_bar_time": None if edge else label,
            "first_seen_time": None, "confirmed_time": None, "earliest_executable_time": None,
            "timing_evidence": "historical_snapshot_only", "bar_completion": "unknown",
            "backtest_eligible": False}
