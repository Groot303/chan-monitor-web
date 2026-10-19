import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts.notification_state import notification_state_path

spec = importlib.util.spec_from_file_location('configure_telegram', Path(__file__).parents[1] / 'deploy' / 'configure_telegram.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = self.root / '.env'
        self.payload = {'TELEGRAM_BOT_TOKEN':'123456:test_token-1','TELEGRAM_CHAT_ID':'-1234'}

    def test_preserves_other_configuration_and_permissions(self):
        self.env.write_text('ALPACA_API_KEY=preserved\n# comment\nTELEGRAM_BOT_TOKEN=old\nTELEGRAM_CHAT_ID=old\n')
        self.assertTrue(c.apply(self.payload, self.env, lambda: True))
        text = self.env.read_text()
        self.assertIn('ALPACA_API_KEY=preserved\n# comment\n',text)
        self.assertEqual(text.count('TELEGRAM_BOT_TOKEN='),1)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode),0o600)

    def test_unchanged_values_do_not_restart(self):
        c.apply(self.payload,self.env,lambda:True)
        def restart(): self.fail('unnecessary restart')
        self.assertFalse(c.apply(self.payload,self.env,restart))

    def test_invalid_payload_does_not_modify_file(self):
        self.env.write_text('EXISTING=value\n')
        for payload in [{**self.payload,'EXTRA':'not allowed'}, {**self.payload,'TELEGRAM_CHAT_ID':'1\nINJECTED=yes'}, {**self.payload,'TELEGRAM_BOT_TOKEN':'invalid'}]:
            with self.assertRaises(ValueError): c.apply(payload,self.env,lambda:True)
        self.assertEqual(self.env.read_text(),'EXISTING=value\n')

    def test_failed_health_restores_original_bytes(self):
        old=b'EXISTING=value\r\n'
        self.env.write_bytes(old)
        calls=[]
        def restart(): calls.append(True); return False
        with self.assertRaises(RuntimeError): c.apply(self.payload,self.env,restart)
        self.assertEqual(self.env.read_bytes(),old)
        self.assertEqual(len(calls),2)

    def test_failed_health_with_new_file_removes_it(self):
        with self.assertRaises(RuntimeError): c.apply(self.payload,self.env,lambda:False)
        self.assertFalse(self.env.exists())

    def test_rejects_symlink(self):
        target=self.root/'target';target.write_text('secret')
        self.env.symlink_to(target)
        with self.assertRaises(ValueError): c.apply(self.payload,self.env,lambda:True)
        self.assertEqual(target.read_text(),'secret')

    def test_migrates_state_once_without_touching_checkout(self):
        repo=self.root/'repo';data=self.root/'api_data'
        (repo/'state').mkdir(parents=True)
        legacy=repo/'state'/'notified.json';legacy.write_text('{"existing":true}')
        target=notification_state_path(repo,data)
        self.assertEqual(target.read_text(),legacy.read_text())
        target.write_text('{"new":true}')
        self.assertEqual(notification_state_path(repo,data).read_text(),'{"new":true}')
        self.assertEqual(legacy.read_text(),'{"existing":true}')


if __name__=='__main__':unittest.main()
