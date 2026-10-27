"""Integration check against the installed exchange_calendars holiday database."""
from paper_market import ExchangeSessions
from paper_trading import timestamp


def main():
    sessions=ExchangeSessions()
    assert sessions.valid('us',timestamp('2026-10-27T13:30:00Z'),timestamp('2026-10-27T13:35:00Z'))
    assert sessions.valid('cn',timestamp('2026-10-27T03:30:00Z'),timestamp('2026-10-27T03:35:00Z')) is None
    assert sessions.session('us','2026-11-26') is None
    assert sessions.session('us','2026-11-27')[1]==timestamp('2026-11-27T18:00:00Z')
    assert sessions.session('cn','2026-10-01') is None
    assert sessions.fresh('us',timestamp('2026-11-27T18:00:00Z'),timestamp('2026-11-28T12:00:00Z'))
    print('PASS: real XNYS/XSHG calendars, holidays, early close, CN lunch and weekend freshness')


if __name__=='__main__':main()
