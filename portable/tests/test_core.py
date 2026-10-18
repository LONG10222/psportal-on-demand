import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from portalproxy.config import DEFAULTS, load, render
from portalproxy.core import CoreManager, CoreError


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class FixtureServerTests(unittest.TestCase):
    def test_loopback_fixture_never_performs_reverse_dns(self):
        from fake_core import API, FixtureHTTPServer
        with patch('socket.getfqdn', side_effect=AssertionError('Unexpected reverse DNS')):
            with FixtureHTTPServer(('127.0.0.1', 0), API) as server:
                self.assertEqual(server.server_name, 'offline-fixture')
                self.assertGreater(server.server_port, 0)


class ConfigTests(unittest.TestCase):
    def test_validation_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = dict(DEFAULTS, listen_host='192.168.1.2', allowed_clients=['192.168.1.3'],
                core_path=str(Path(__file__).with_name('fake_core.py').resolve()), subscription_url='https://example.com/private?token=secret')
            path = Path(tmp)/'config.json'
            path.write_text(json.dumps(cfg))
            validated = load(path)
            rendered = render(validated, 'a'*64)
            self.assertFalse(rendered['allow-lan'])
            self.assertFalse(rendered['tun']['enable'])
            self.assertNotIn('subscription_url', rendered)
            self.assertEqual(rendered['rules'][-1], 'MATCH,PORTAL')
            for key, value in [('listen_host','0.0.0.0'),('allowed_clients',['127.0.0.1']),('subscription_url','http://example.com'),('selection_mode','fixed'),('backend_port',10081)]:
                path.write_text(json.dumps(dict(cfg, **{key:value})))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load(path)


@unittest.skipIf(os.name == 'nt', 'POSIX shebang fixture; native Windows test uses built executable')
class CoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = dict(DEFAULTS, data_dir=self.tmp.name, backend_port=port(), api_port=port(),
            core_path=str(Path(__file__).with_name('fake_core.py').resolve()),
            # Hosted macOS Python may need longer for two fresh fixture processes.
            # This remains below the app's production startup budget (45 seconds).
            subscription_url='https://example.com/private', idle_seconds=1, wakeup_timeout=15)
        def download(url, path):
            path.write_text('proxies: []\n')
        self.patch = patch('portalproxy.core.download_subscription', download)
        self.patch.start()
        self.core = CoreManager(self.cfg)
    async def asyncTearDown(self):
        await self.core.close()
        self.patch.stop()
        self.tmp.cleanup()
    async def test_concurrent_wake_idle_and_rewake(self):
        self.core.start_monitor()
        results = await asyncio.gather(*(self.core.acquire() for _ in range(8)))
        first = self.core.process.pid
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(self.core.active, 8)
        await asyncio.sleep(1.2)
        self.assertEqual(self.core.process.pid, first)
        await asyncio.gather(*(self.core.release() for _ in range(8)))
        for _ in range(30):
            if self.core.process is None:
                break
            await asyncio.sleep(.1)
        self.assertIsNone(self.core.process)
        await self.core.acquire()
        self.assertNotEqual(self.core.process.pid, first)
        await self.core.release()
    async def test_missing_fixed_node_stops_owned_core(self):
        self.cfg.update(selection_mode='fixed', preferred_node='missing')
        with self.assertRaisesRegex(CoreError, 'Fixed node'):
            await self.core.acquire()
        self.assertIsNone(self.core.process)
        self.assertEqual(self.core.active, 0)
    async def test_preferred_selection(self):
        self.cfg.update(selection_mode='fixed', preferred_node='Tokyo')
        await self.core.acquire()
        selected = await asyncio.to_thread(self.core._request, '/proxies/PORTAL')
        self.assertEqual(selected['now'], 'Tokyo')
        await self.core.release()
    async def test_startup_error_is_visible_and_redacted(self):
        log = io.StringIO()
        with patch('portalproxy.core.download_subscription', side_effect=OSError('secret-token')), contextlib.redirect_stdout(log):
            with self.assertRaises(CoreError):
                await self.core.acquire()
        self.assertIn('Core startup failed:', log.getvalue())
        self.assertNotIn('secret-token', log.getvalue())

    async def test_refuses_other_owner(self):
        with self.assertRaises(CoreError):
            CoreManager(self.cfg)
    async def test_occupied_backend_fails_without_touching_it(self):
        with socket.socket() as other:
            other.bind(('127.0.0.1', self.cfg['backend_port']))
            other.listen()
            with self.assertRaises(CoreError):
                await self.core.acquire()
            self.assertGreaterEqual(other.fileno(), 0)
        self.assertIsNone(self.core.process)


if __name__ == '__main__':
    unittest.main()

class SubscriptionTests(unittest.TestCase):
    def test_failed_download_redacts_url_and_preserves_cache(self):
        from portalproxy.core import download_subscription
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'subscription.yaml'
            path.write_text('old')
            with patch('socket.getaddrinfo', side_effect=OSError('https://secret-token')):
                with self.assertRaises(CoreError) as raised:
                    download_subscription('https://example.com/secret-token', path)
            self.assertNotIn('secret-token', str(raised.exception))
            self.assertEqual(path.read_text(), 'old')
    def test_redirects_fail_closed(self):
        from portalproxy.core import NoRedirect
        with self.assertRaises(CoreError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'http://unsafe')
