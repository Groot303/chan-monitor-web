import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cn_export_test', ROOT / 'scripts' / 'export_chart.py')
chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chart)


class CNChartExportTests(unittest.TestCase):
    def test_market_timezone_preserves_daily_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.csv'
            df = pd.DataFrame({'Open':[10.0],'High':[11.0],'Low':[9.0],'Close':[10.5],'Volume':[100]}, index=pd.DatetimeIndex(['2026-10-21 00:00:00+08:00']))
            df.to_csv(path)
            cn = chart.load_df(str(path), tz='Asia/Shanghai')
            self.assertEqual(chart.bar_time(cn.index[0], 'daily'), '2026-10-21')
            us = chart.load_df(str(path))
            self.assertEqual(chart.bar_time(us.index[0], 'daily'), '2026-10-20')
            self.assertEqual(chart.bar_time(cn.index[0],'5m'), chart.bar_time(us.index[0],'5m'))

    def test_cn_build_retains_leading_zero_code_and_exports_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'input'; dst = Path(tmp) / 'built'; src.mkdir()
            idx = pd.date_range('2026-07-01',periods=80,freq='D',tz='Asia/Shanghai')
            df = pd.DataFrame({'Open':[10+i*.01 for i in range(80)],'High':[11+i*.01 for i in range(80)],'Low':[9+i*.01 for i in range(80)],'Close':[10.5+i*.01 for i in range(80)],'Volume':[100]*80},index=idx)
            df.to_csv(src / 'data2_万向钱潮_daily.csv')
            meta={'bars':80,'first':'2026-07-01','last':str(idx[-1].date()),'last_close':11.29,'state':{},'last_segment':None,'signals':[]}
            (src/'signals.json').write_text(json.dumps({'generated':'2026-10-21','market':'cn','symbols':{'万向钱潮':{'code':'000559','levels':{'daily':meta}}}}))
            result = subprocess.run([sys.executable,str(ROOT/'scripts/build_data.py'),str(src),'--market','cn','--outdir',str(dst)],cwd=ROOT,text=True,capture_output=True,check=True)
            data=json.loads((dst/'data/signals_cn.json').read_text())
            self.assertEqual(data['symbols']['万向钱潮']['code'],'000559')
            payload=json.loads((dst/'data/charts_cn/万向钱潮.json').read_text())
            self.assertEqual(payload['levels']['daily']['ohlc'][-1]['time'],str(idx[-1].date()))
            self.assertIn('chart 万向钱潮: ok',result.stdout)


if __name__=='__main__': unittest.main()
