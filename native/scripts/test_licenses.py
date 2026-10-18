# SPDX-License-Identifier: GPL-3.0-only
"""License/source collection must never turn a download failure into success."""
import contextlib
import io
import subprocess
import unittest
from unittest.mock import patch
import licenses


class MetadataRetryTests(unittest.TestCase):
    def setUp(self):
        self.stderr = contextlib.redirect_stderr(io.StringIO())
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_dns_retry_preserves_command_and_returns_complete_output(self, run, sleep):
        command = ['go', 'list', '-m', '-json', 'all']
        run.side_effect = [subprocess.CalledProcessError(1, command, output='partial', stderr='lookup proxy.golang.org: no such host'), subprocess.CompletedProcess(command, 0, '{"complete":true}', '')]
        self.assertEqual(licenses.network_output(command), '{"complete":true}')
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args[0] == command for call in run.call_args_list))
        sleep.assert_called_once_with(2)

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_repeated_dns_failure_is_bounded_and_fails_closed(self, run, sleep):
        run.side_effect = subprocess.CalledProcessError(1, ['go'], stderr='i/o timeout')
        with self.assertRaises(subprocess.CalledProcessError): licenses.network_output(['go'])
        self.assertEqual(run.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_timeout_is_bounded_and_fails_closed(self, run, sleep):
        run.side_effect = subprocess.TimeoutExpired(['go'], 120)
        with self.assertRaises(subprocess.TimeoutExpired): licenses.network_output(['go'])
        self.assertEqual(run.call_count, 3)
        self.assertTrue(all(c.kwargs['timeout'] == 120 for c in run.call_args_list))

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_integrity_or_permission_failure_never_retries(self, run, sleep):
        for message in ('checksum mismatch; i/o timeout', 'SECURITY ERROR: no such host', '403 Forbidden; connection reset', 'x509: unknown authority'):
            with self.subTest(message=message):
                run.reset_mock(); run.side_effect = subprocess.CalledProcessError(1, ['go'], stderr=message)
                with self.assertRaises(subprocess.CalledProcessError): licenses.network_output(['go'])
                self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.subprocess.run')
    def test_non_network_failure_never_retries(self, run):
        run.side_effect = subprocess.CalledProcessError(1, ['go'], stderr='unknown revision v1.2.3')
        with self.assertRaises(subprocess.CalledProcessError): licenses.network_output(['go'])
        self.assertEqual(run.call_count, 1)

    @patch('licenses.subprocess.run')
    def test_invalid_attempt_budget_rejected(self, run):
        for attempts in (0, 4):
            with self.assertRaises(ValueError): licenses.network_output(['go'], attempts=attempts)
        run.assert_not_called()


if __name__ == '__main__': unittest.main()
