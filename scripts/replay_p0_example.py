"""Reproducible synthetic evidence, not performance research.
Run: python -m scripts.replay_p0_example --output /tmp/p0-replay.json
"""
import argparse
import json
from collections import Counter
import numpy as np
import pandas as pd
from signal_replay import replay


def fixture(bars=360):
    close = 100 + np.cumsum(np.random.default_rng(3).normal(0, 1, bars))
    index = pd.date_range("2025-01-01", periods=bars, freq="30min", tz="UTC")
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close}, index=index)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    df = fixture()
    result = replay(df, available_at=df.index + pd.Timedelta(minutes=30),
                    open_times=df.index, complete=[True] * len(df))
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(dict(Counter(event["event"] for event in result["events"])))


if __name__ == "__main__":
    main()
