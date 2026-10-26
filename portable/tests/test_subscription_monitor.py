import tempfile
import threading
import time
import unittest
from pathlib import Path
from portalproxy.subscription_monitor import AccountingMonitor, descriptor
from portalproxy.existing_proxy import clash_subscription_source


class AccountingRefreshTests(unittest.TestCase):
    def settle(self,monitor,source):
        deadline=time.monotonic()+3
        while monitor.busy and time.monotonic()<deadline:
            monitor.tick(source);time.sleep(.01)
        self.assertFalse(monitor.busy)

    def test_periodic_refresh_keeps_source_and_unknown_quota_honest(self):
        now=[0];calls=[]
        def loader(url):calls.append(url);return {'upload':len(calls),'download':2,'total':100,'updated_at':10}
        source=descriptor('https://example.invalid/private',identity='one')
        monitor=AccountingMonitor(loader,lambda:now[0]);monitor.tick(source);self.settle(monitor,source)
        self.assertEqual(monitor.info['upload'],1)
        now[0]=59;monitor.tick(source);self.assertEqual(len(calls),1)
        now[0]=61;monitor.tick(source);self.settle(monitor,source)
        self.assertEqual(monitor.info['upload'],2)
        self.assertNotIn('/private',str(monitor.info))

    def test_late_results_cannot_overwrite_new_subscription(self):
        gate=threading.Event()
        def loader(url):
            if url.endswith('/old'):gate.wait(2);return {'total':100}
            return {'total':200}
        old=descriptor('https://example.invalid/old',identity='old')
        new=descriptor('https://example.invalid/new',identity='new')
        monitor=AccountingMonitor(loader);monitor.tick(old);monitor.tick(new)
        gate.set();self.settle(monitor,new)
        self.assertEqual(monitor.info['total'],200)

    def test_failed_refresh_retains_original_timestamp_and_values(self):
        source=descriptor('https://example.invalid/sub',{'total':100,'updated_at':5})
        monitor=AccountingMonitor(lambda url:None);monitor.tick(source);self.settle(monitor,source)
        self.assertEqual(monitor.info['updated_at'],5)
        self.assertIn('保留',monitor.message)

    def test_clash_reads_only_current_profile_and_keeps_url_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'profiles.yaml'
            path.write_text('current: active\nitems:\n - uid: other\n   url: https://other.invalid/sub\n - uid: active\n   name: Current\n   url: https://provider.invalid/credential\n   extra: {upload: 1, download: 2, total: 10}\n')
            result=clash_subscription_source(path)
            self.assertEqual(result['url'],'https://provider.invalid/credential')
            self.assertEqual(result['cached']['total'],10)
            self.assertNotIn('credential',str(result['cached']))

    def test_metadata_refresh_rejects_unsafe_destinations_and_schemes(self):
        for url in ('http://example.com/','https://u:p@example.com/','https://example.com/#token','https://example.com:444/'):
            self.assertEqual(descriptor(url)['url'],'')
