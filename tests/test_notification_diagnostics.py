import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.notification_diagnostics import diagnose, telegram_probe


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.data = self.base / 'api_data'
        (self.repo / 'state').mkdir(parents=True)
        (self.data / 'data').mkdir(parents=True)
        self.signal = dict(symbol='TEST',level='5m',type='3B',time='2026-10-19',score=5,recent=True,confirmed=True)
        for name in ('signals.json','signals_cn.json'):
            (self.data / 'data' / name).write_text(json.dumps({'generated':'2026-10-19','signals':[self.signal]}))

    def test_missing_configuration_does_not_call_telegram(self):
        def probe(*args):
            self.fail('unconfigured bot must not contact Telegram')
        result = diagnose(self.repo,self.data,{},probe)
        self.assertFalse(result['token_configured'])
        self.assertFalse(result['chat_configured'])
        self.assertEqual(result['markets']['signals.json']['pending'],1)
        self.assertFalse(result['message_sent'])

    def test_dedup_and_no_state_writes_or_secret_output(self):
        state = self.repo / 'state' / 'notified.json'
        content = json.dumps({'TEST|5m|3B|2026-10-19':{'confirmed':True,'score':5}})
        state.write_text(content)
        calls=[]
        def probe(*args):
            calls.append(len(args));return {'ok':True}
        result = diagnose(self.repo,self.data,{'TELEGRAM_BOT_TOKEN':'secret-token','TELEGRAM_CHAT_ID':'private-chat-id'},probe)
        self.assertEqual(result['markets']['signals.json']['pending'],0)
        self.assertEqual(result['markets']['signals.json']['eligible'],1)
        self.assertEqual(calls,[1,2])
        self.assertEqual(state.read_text(),content)
        serialized=json.dumps(result)
        self.assertNotIn('secret-token',serialized)
        self.assertNotIn('private-chat-id',serialized)

    def test_log_output_is_allowlisted(self):
        (self.base / 'logs').mkdir()
        (self.base / 'logs' / 'api.log').write_text('notify[signals.json]: notify error: HTTPError secret-token\nnotify[signals_cn.json]: no new signals to notify; secret-token\n')
        result=diagnose(self.repo,self.data,{})
        self.assertEqual(result['recent_outcomes'],{'signals.json':'telegram_http_error','signals_cn.json':'no_new_signals'})
        self.assertNotIn('secret-token',json.dumps(result))

    def test_invalid_threshold_stops_probes(self):
        result=diagnose(self.repo,self.data,{'SCORE_MIN':'oops'})
        self.assertEqual(result['configuration_error'],'invalid_score_min')

    def test_http_errors_are_classified_without_url(self):
        error=HTTPError('https://api.telegram.org/botsecret/getChat',400,'bad request',{},io.BytesIO(json.dumps({'ok':False,'error_code':400,'description':'Bad Request: chat not found'}).encode()))
        with patch('scripts.notification_diagnostics.urllib.request.urlopen',side_effect=error):
            result=telegram_probe('secret','private-chat')
        self.assertEqual(result,{'ok':False,'reason':'chat_not_found','error_code':400})


if __name__=='__main__':
    unittest.main()
