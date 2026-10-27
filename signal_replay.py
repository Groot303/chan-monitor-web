"""Prefix-only replay with explicit availability/completion evidence.

No inferred session calendar, fills, fees, multi-timeframe joins or P1 entry rules.
"""
import json
import pandas as pd
import numpy as np
from chan2 import analyze_level
from signal_safety import confirmation_contract


def _times(values, name, length):
    if len(values) != length:
        raise ValueError(f"{name}: length mismatch")
    result = [pd.Timestamp(x) for x in values]
    if any(pd.isna(x) or x.tzinfo is None for x in result):
        raise ValueError(f"{name}: explicit timezone required")
    if any(b <= a for a, b in zip(result, result[1:])):
        raise ValueError(f"{name}: must be strictly increasing")
    return result


def replay(df, *, available_at, complete, open_times=None, level="30m"):
    """Every analysis receives only complete bars available at that step.

    available_at must be evidenced bar-final availability, not a guessed label.
    open_times optionally enables next-observed-bar execution-window evidence.
    Times reflect this supplied dataset/model, not real historic feed latency.
    """
    n = len(df)
    labels = _times(df.index, "bar labels", n)
    available = _times(available_at, "available_at", n)
    opens = _times(open_times, "open_times", n) if open_times is not None else None
    if len(complete) != n or any(type(x) is not bool for x in complete):
        raise ValueError("explicit boolean completion evidence required for every bar")
    if any(a < label for a, label, done in zip(available, labels, complete) if done):
        raise ValueError("complete bar cannot be available before its label")
    if opens and any(o > a for o, a in zip(opens, available)):
        raise ValueError("bar open cannot follow its availability")
    if any(not x for x in complete[:-1]):
        raise ValueError("incomplete interior bar: supply chronological final revisions instead")
    required = ["Open", "High", "Low", "Close"]
    if any(c not in df for c in required):
        raise ValueError("missing OHLC column")
    values = df.loc[:, required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("missing or invalid OHLC: replay must not bridge missing bars")
    if ((values[:, 1] < values[:, [0, 2, 3]].max(axis=1)) |
            (values[:, 2] > values[:, [0, 1, 3]].min(axis=1))).any():
        raise ValueError("inconsistent OHLC")
    active, events, snapshots, rows = {}, [], [], []
    serial = 0
    for i in range(n):
        if not complete[i]:
            continue
        # A window is appended only when a later observed bar arrives; never erase it
        # because the detector subsequently repaints or invalidates a historical touch.
        if opens:
            for record in active.values():
                if record["earliest_executable_time"] is None and opens[i] > record["seen_at"]:
                    record["earliest_executable_time"] = opens[i].isoformat()
                    events.append({"event": "execution_window", "id": record["id"],
                                   "time": opens[i].isoformat(), "meaning": "timing_only_not_entry_or_fill"})
        rows.append(i)
        prefix = df.iloc[rows].copy()
        result = analyze_level(prefix, level=level)
        current = {}
        for signal in result["signals"]:
            # PRE -> classic may be a structural-confirmation transition. Changed
            # extrema/price/pivot bounds are separate candidates, never merged blindly.
            identity = (signal["type"].removeprefix("PRE_"), labels[rows[signal["idx"]]].isoformat(),
                        float(signal["price"]), signal.get("zg"), signal.get("zd"), signal.get("kind"))
            key = json.dumps(identity)
            if key in current:
                raise ValueError("ambiguous duplicate signal identity; need pivot provenance")
            contract = confirmation_contract(signal)
            record = active.get(key)
            if record is None:
                serial += 1
                record = {"id": serial, "seen_at": available[i], "first_seen_time": available[i].isoformat(),
                          "confirmed_time": None, "earliest_executable_time": None}
                events.append({"event": "first_seen", "id": serial, "time": available[i].isoformat(),
                               "signal_bar_time": identity[1],
                               "extreme_bar_time": identity[1] if contract["touch_confirmed"] is None else None,
                               "signal": dict(signal)})
            if contract["structure_confirmed"] and not record.get("structure_confirmed"):
                if record["confirmed_time"] is None:
                    record["confirmed_time"] = available[i].isoformat()
                events.append({"event": "structure_confirmed", "id": record["id"], "time": available[i].isoformat()})
            elif record.get("structure_confirmed") and contract["structure_confirmed"] is False:
                events.append({"event": "confirmation_revoked", "id": record["id"], "time": available[i].isoformat()})
            record.update(contract)
            record.update(signal_type=signal["type"], signal_bar_time=identity[1],
                          extreme_bar_time=identity[1] if contract["touch_confirmed"] is None else None,
                          price=float(signal["price"]))
            current[key] = record
        for key in active.keys() - current.keys():
            events.append({"event": "disappeared", "id": active[key]["id"], "time": available[i].isoformat(),
                           "reason": "absent_from_prefix_recalculation_not_proof_of_trade_cancellation"})
        snapshots.append({"as_of": available[i].isoformat(), "bars": len(prefix),
                          "signals": [{k: v for k, v in r.items() if k != "seen_at"} for r in current.values()]})
        active = current
    return {"timing_evidence": "prefix_replay_with_supplied_availability",
            "execution_model": "first_observed_open_strictly_after_detection_no_fill_assumption", "events": events, "snapshots": snapshots}
