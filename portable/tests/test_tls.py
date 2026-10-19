import os
from pathlib import Path
import ssl
import sys
import unittest
from unittest.mock import Mock, patch

from portalproxy.tls import verified_context


class VerifiedContextTests(unittest.TestCase):
    def context(self, count):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        stub = Mock(wraps=context)
        stub.cert_store_stats.return_value = {'x509_ca': count}
        stub.load_verify_locations = Mock()
        return stub

    def test_empty_mac_store_loads_only_the_existing_os_ca_file(self):
        context = self.context(0)
        with (patch('portalproxy.tls.ssl.create_default_context', return_value=context),
              patch('portalproxy.tls.sys.platform', 'darwin'),
              patch('portalproxy.tls.Path.is_file', return_value=True),
              patch.dict(os.environ, {}, clear=True)):
            self.assertIs(verified_context(), context)
        context.load_verify_locations.assert_called_once_with(cafile='/etc/ssl/cert.pem')
        self.assertEqual(context._mock_wraps.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context._mock_wraps.check_hostname)

    def test_loaded_roots_overrides_other_platforms_and_absent_file_are_preserved(self):
        for platform, count, environment, exists in (
                ('darwin', 1, {}, True), ('darwin', 0, {'SSL_CERT_FILE':'/custom.pem'}, True),
                ('darwin', 0, {'SSL_CERT_DIR':'/custom'}, True), ('linux', 0, {}, True),
                ('win32', 0, {}, True), ('darwin', 0, {}, False)):
            with self.subTest(platform=platform, environment=environment, count=count):
                context = self.context(count)
                with (patch('portalproxy.tls.ssl.create_default_context', return_value=context),
                      patch('portalproxy.tls.sys.platform', platform),
                      patch('portalproxy.tls.Path.is_file', return_value=exists),
                      patch.dict(os.environ, environment, clear=True)):
                    verified_context()
                context.load_verify_locations.assert_not_called()

    @unittest.skipUnless(sys.platform == 'darwin' and Path('/etc/ssl/cert.pem').is_file(),
                         'Real macOS system CA file required')
    def test_real_context_has_roots_and_keeps_both_verification_checks(self):
        with patch.dict(os.environ, {}, clear=True):
            context = verified_context()
        self.assertGreater(context.cert_store_stats()['x509_ca'], 0)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
