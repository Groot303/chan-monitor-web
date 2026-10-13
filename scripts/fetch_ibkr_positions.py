#!/usr/bin/env python3
"""Fetch IBKR open positions via Flex Web Service -> site/data/positions_ibkr.json.

Flow: SendRequest (get reference code) -> poll GetStatement until the report
is ready -> parse <OpenPositions> -> write JSON consumed by run2.py and the
frontend.

Config via environment (same .env as the pipeline):
    IBKR_FLEX_TOKEN      read-only Flex Web Service token (from Client Portal)
    IBKR_FLEX_QUERY_ID   numeric Activity Flex Query id (must include Open Positions)
    POSITIONS_OUT        output path (default: site/data/positions_ibkr.json)

The token is read-only: Flex exposes only report retrieval, no order surface.
Run `--selftest` to verify XML parsing without credentials.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
HEADERS = {"User-Agent": "Python/3"}
POLL_INTERVAL = 5
POLL_TIMEOUT = 180


def _http(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _num(el: ET.Element, *names, default=0.0) -> float:
    for n in names:
        v = el.get(n)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                pass
    return default


def send_request(token: str, query_id: str) -> str:
    url = (f"{BASE}/SendRequest?t={urllib.parse.quote(token)}"
           f"&q={urllib.parse.quote(query_id)}&v=3")
    root = ET.fromstring(_http(url))
    if root.findtext("Status") != "Success":
        raise SystemExit(
            f"SendRequest failed: {root.findtext('ErrorCode')} "
            f"{root.findtext('ErrorMessage')}")
    ref = root.findtext("ReferenceCode")
    if not ref:
        raise SystemExit("SendRequest succeeded but returned no ReferenceCode")
    return ref


def get_statement(token: str, refcode: str) -> ET.Element:
    """Poll GetStatement until the report XML is ready (1019 = generating)."""
    url = (f"{BASE}/GetStatement?t={urllib.parse.quote(token)}"
           f"&q={urllib.parse.quote(refcode)}&v=3")
    deadline = time.time() + POLL_TIMEOUT
    while True:
        root = ET.fromstring(_http(url))
        # v3 wraps the report as <FlexQueryResponse><FlexStatements>...</FlexStatements>
        # (older/docs examples show a bare <FlexStatements> root).
        if root.tag in ("FlexQueryResponse", "FlexStatements") or root.find(".//FlexStatement") is not None:
            return root
        code = root.findtext("ErrorCode")
        if code == "1019":  # generation in progress -> keep polling
            if time.time() > deadline:
                raise SystemExit("GetStatement timed out waiting for report generation")
            time.sleep(POLL_INTERVAL)
            continue
        raise SystemExit(
            f"GetStatement failed: {code} {root.findtext('ErrorMessage')}")


def parse_positions(root: ET.Element) -> dict:
    positions = []
    accounts = set()
    report_date = ""
    for stmt in root.iter("FlexStatement"):
        report_date = stmt.get("toDate") or stmt.get("fromDate") or report_date
        for op in stmt.iter("OpenPosition"):
            acct = op.get("accountId", "")
            accounts.add(acct)
            asset = op.get("assetCategory", "")
            # Options/futures -> track the underlying so the symbol list stays tradeable
            symbol = op.get("underlyingSymbol") or op.get("symbol", "")
            if asset == "STK":
                symbol = op.get("symbol", "")
            qty = _num(op, "position")
            if not symbol or qty == 0:
                continue
            positions.append({
                "symbol": symbol,
                "asset": asset,
                "currency": op.get("currency", ""),
                "qty": qty,
                "cost": _num(op, "costBasisPrice"),
                "mark": _num(op, "markPrice"),
                "value": _num(op, "positionValue", "costBasisMoney"),
                "unrealized": _num(op, "fifoPnlUnrealized", "unrealizedPnl"),
                "account": acct,
            })
    # STK first, then everything else, deduped, stable order
    seen, symbols = set(), []
    for p in sorted(positions, key=lambda p: (0 if p["asset"] == "STK" else 1, p["symbol"])):
        if p["symbol"] not in seen:
            seen.add(p["symbol"])
            symbols.append(p["symbol"])
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_date": report_date,
        "accounts": sorted(accounts),
        "symbols": symbols,
        "positions": positions,
    }


def main() -> None:
    if "--selftest" in sys.argv:
        sample = """<FlexStatements count="1"><FlexStatement toDate="20261013" accountId="U1234567">
        <OpenPositions>
        <OpenPosition accountId="U1234567" currency="USD" assetCategory="STK" symbol="AAPL"
            position="100" costBasisPrice="220.50" markPrice="235.10" positionValue="23510"
            fifoPnlUnrealized="1460" underlyingSymbol=""/>
        <OpenPosition accountId="U1234567" currency="USD" assetCategory="OPT" symbol="NVDA  260117P00250000"
            position="2" costBasisPrice="3.20" markPrice="4.10" positionValue="820"
            fifoPnlUnrealized="180" underlyingSymbol="NVDA"/>
        <OpenPosition accountId="U1234567" currency="USD" assetCategory="STK" symbol="TSLA"
            position="0" costBasisPrice="0" markPrice="250" positionValue="0"
            fifoPnlUnrealized="0" underlyingSymbol=""/>
        </OpenPositions></FlexStatement></FlexStatements>"""
        out = parse_positions(ET.fromstring(sample))
        assert out["symbols"] == ["AAPL", "NVDA"], out["symbols"]
        assert len(out["positions"]) == 2, out["positions"]
        assert out["positions"][0]["unrealized"] == 1460.0
        print("selftest OK:", json.dumps(out["symbols"]))
        return

    token = os.environ.get("IBKR_FLEX_TOKEN", "")
    query_id = os.environ.get("IBKR_FLEX_QUERY_ID", "")
    if not token or not query_id:
        raise SystemExit("IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID not set")
    out_path = os.environ.get("POSITIONS_OUT", "site/data/positions_ibkr.json")

    refcode = send_request(token, query_id)
    root = get_statement(token, refcode)
    data = parse_positions(root)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, out_path)
    print(f"wrote {out_path}: {len(data['symbols'])} symbols {data['symbols']}")


if __name__ == "__main__":
    main()
