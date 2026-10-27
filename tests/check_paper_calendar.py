"""Integration check against the installed exchange_calendars holiday database."""
from paper_market import ExchangeSessions
from paper_trading import timestamp
from strategy_source import FileStrategySource
from datetime import timedelta
from pathlib import Path


def main():
    sessions=ExchangeSessions()
    assert sessions.valid('us',timestamp('2026-10-27T13:30:00Z'),timestamp('2026-10-27T13:35:00Z'))
    assert sessions.valid('cn',timestamp('2026-10-27T03:30:00Z'),timestamp('2026-10-27T03:35:00Z')) is None
    assert sessions.session('us','2026-11-26') is None
    assert sessions.session('us','2026-11-27')[1]==timestamp('2026-11-27T18:00:00Z')
    assert sessions.session('cn','2026-10-01') is None
    assert sessions.fresh('us',timestamp('2026-11-27T18:00:00Z'),timestamp('2026-11-28T12:00:00Z'))
    # 自动策略的30分钟历史在真实提前收盘处结束；休市日不要求虚构K线。
    rows=[dict(time=(timestamp('2026-11-27T14:30:00Z')+timedelta(minutes=30*i)).isoformat(),
               open=100,high=102,low=99,close=101) for i in range(7)]
    frame=FileStrategySource(Path('/unused'),sessions).closed_frame(rows,'30m',timestamp('2026-11-28T12:00:00Z'),minimum=1)
    assert len(frame)==7
    print('PASS: real XNYS/XSHG calendars, holidays, early close, CN lunch and weekend freshness')


if __name__=='__main__':main()
