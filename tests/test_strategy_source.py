import copy
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from paper_trading import timestamp
from strategy_source import FileStrategySource, SCHEMA, build_source
from paper_market import FileMarketData


class Sessions:
    """固定常规时段，仅供确定性测试；生产使用真实XNYS日历。"""
    def session(self,market,day):
        start=timestamp(day+'T13:30:00Z')
        return (start,start+timedelta(hours=6,minutes=30),None) if start.weekday()<5 else None


def source_fixture():
    rows=[]
    for day in pd.bdate_range('2025-10-01','2026-10-27'):
        rows.append(dict(time=day.strftime('%Y-%m-%d')+'T05:00:00+00:00',open=100.,high=102.,low=99.,close=101.))
    intraday=[]
    for day in pd.bdate_range('2026-10-19','2026-10-27'):
        for i in range(13):
            opened=timestamp(day.strftime('%Y-%m-%d')+'T13:30:00Z')+timedelta(minutes=i*30)
            intraday.append(dict(time=opened.isoformat(),open=100.,high=102.,low=99.,close=101.))
    return dict(schema=SCHEMA,observed_at='2026-10-27T14:30:00Z',generated='2026-10-27T14:31:00Z',
        benchmark={'observed_at':'2026-10-27T14:30:00Z','bars':copy.deepcopy(rows)},
        symbols={'AAPL':{'daily':rows,'30m':intraday}})


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'source.json'
        self.data=source_fixture();self.source=FileStrategySource(self.path,Sessions())
        self.now=timestamp('2026-10-27T14:31:00Z')
    def tearDown(self):self.tmp.cleanup()
    def read(self):
        self.path.write_text(json.dumps(self.data));return self.source.read(self.now)

    def test_completed_prefix_is_recomputed_with_original_detector(self):
        result=self.read()
        self.assertNotIn('error',result)
        self.assertTrue(result['symbols']['AAPL']['valid'])
        self.assertEqual(result['symbols']['AAPL']['last_completed_bar'],'2026-10-27T13:30:00+00:00')
        self.assertEqual(result['context']['new_long_environment'],'permitted')
        # 未收盘及稳定缓冲内数据任意改动，都不能进入检测器。
        before=copy.deepcopy(result['symbols']['AAPL'])
        self.data['symbols']['AAPL']['30m'][-1]['close']=1000000
        self.data['symbols']['AAPL']['daily'][-1]['close']=1000000
        after=self.read()
        self.assertEqual(before,after['symbols']['AAPL'])
        self.assertEqual(result['regime'],after['regime'])

    def test_gap_bad_price_duplicate_and_tail_staleness_fail_closed(self):
        base=copy.deepcopy(self.data)
        changes=[lambda data:data['symbols']['AAPL']['30m'].pop(20),
                 lambda data:data['symbols']['AAPL']['30m'][20].update(low=float('nan')),
                 lambda data:data['symbols']['AAPL']['30m'].insert(21,copy.deepcopy(data['symbols']['AAPL']['30m'][20])),
                 lambda data:data['symbols']['AAPL']['daily'].pop(-2)]
        for change in changes:
            self.data=copy.deepcopy(base);change(self.data)
            self.assertFalse(self.read()['symbols']['AAPL']['valid'])

    def test_missing_benchmark_is_unknown_not_non_bear_and_old_source_rejected(self):
        self.data['benchmark']=None
        result=self.read();self.assertEqual(result['context']['new_long_environment'],'unknown')
        self.assertFalse(result['regime']['bear']);self.assertFalse(result['regime']['known'])
        self.data.pop('observed_at');self.assertIn('error',self.read())
        self.data=[];self.assertIn('error',self.read())
        self.path.write_text('{bad json');self.assertIn('error',self.source.read(self.now))

    def test_cached_valid_snapshot_still_expires_and_future_source_is_unknown(self):
        self.assertNotIn('error',self.read())
        self.now+=timedelta(minutes=46)
        self.assertIn('error',self.source.read(self.now))
        self.now=timestamp('2026-10-27T14:29:00Z');self.assertIn('error',self.source.read(self.now))

    def test_missing_calendar_is_unknown(self):
        self.source.sessions=type('Offline',(),{'session':lambda *a:None})()
        result=self.read()
        self.assertFalse(result['symbols']['AAPL']['valid'])
        self.assertEqual(result['context']['new_long_environment'],'unknown')

    def test_legacy_chart_with_missing_5m_level_is_unknown_not_crash(self):
        root=Path(self.tmp.name);(root/'charts').mkdir()
        market=FileMarketData(root,Sessions())
        for value in (None,{}, {'ohlc':None}):
            (root/'charts/AAPL.json').write_text(json.dumps({'levels':{'5m':value}}))
            self.assertEqual(market.bars('us','AAPL',self.now),[])

    def test_pipeline_serialization_keeps_source_time_and_excludes_index(self):
        frame=self.source.closed_frame(self.data['symbols']['AAPL']['daily'],'daily',timestamp('2026-10-27T14:15:00Z'))
        source=build_source({'daily':{'AAPL':frame,'纳指':frame}},None,'2026-10-27T14:30:00Z','2026-10-27T14:31:00Z')
        self.assertEqual(source['observed_at'],'2026-10-27T14:30:00Z')
        self.assertNotIn('纳指',source['symbols']);self.assertTrue(source['symbols']['AAPL']['daily'])
        self.assertEqual(build_source({},None,None,'now')['observed_at'],None)


if __name__=='__main__':unittest.main()
