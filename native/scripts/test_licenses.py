# SPDX-License-Identifier: GPL-3.0-only
"""License/source collection must never turn a download failure into success."""
import contextlib
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import licenses


class MetadataRetryTests(unittest.TestCase):
    def setUp(self):
        self.diagnostics = io.StringIO()
        self.stderr = contextlib.redirect_stderr(self.diagnostics)
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
    def test_darwin_connect_timeout_retries_without_weakening_fatal_gate(self, run, sleep):
        failed = json.dumps(dict(Error='Get https://proxy.golang.org/module.zip: dial tcp 192.0.2.1:443: connect: operation timed out'))
        run.side_effect = [subprocess.CalledProcessError(1, ['go'], output=failed, stderr=''),
                           subprocess.CompletedProcess(['go'], 0, 'complete', '')]
        self.assertEqual(licenses.network_output(['go']), 'complete')
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(2)

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_download_json_error_retries_with_empty_stderr(self, run, sleep):
        command = ['go', 'mod', 'download', '-json', 'github.com/mdlayher/packet@v1.1.2']
        message = 'github.com/mdlayher/packet@v1.1.2: proxy.golang.org: i/o timeout'
        failed = json.dumps(dict(Path='github.com/mdlayher/packet', Version='v1.1.2', Error=message))
        complete = json.dumps(dict(Dir='/module/cache/packet@v1.1.2'))
        env = {'GOOS': 'linux', 'GOARCH': 'arm64'}
        run.side_effect = [subprocess.CalledProcessError(1, command, output=failed, stderr=''),
                           subprocess.CompletedProcess(command, 0, complete, '')]
        self.assertEqual(licenses.network_output(command, env=env), complete)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0], command)
            self.assertEqual(call.kwargs['env'], env)
            self.assertEqual(call.kwargs['cwd'], licenses.ROOT)
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertTrue(call.kwargs['check'])
        self.assertIn(message, self.diagnostics.getvalue())
        sleep.assert_called_once_with(2)

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_json_error_exhaustion_preserves_exception_and_output(self, run, sleep):
        failed = json.dumps(dict(Error='503 Service Unavailable'))
        error = subprocess.CalledProcessError(1, ['go'], output=failed, stderr='')
        run.side_effect = error
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            licenses.network_output(['go'])
        self.assertIs(caught.exception, error)
        self.assertEqual(caught.exception.stdout, failed)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])
        self.assertEqual(self.diagnostics.getvalue().count('503 Service Unavailable'), 3)

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_go_list_json_error_object_is_retryable(self, run, sleep):
        failed = json.dumps(dict(Path='example/ready')) + '\n' + json.dumps(dict(Error=dict(Err='connection reset')))
        run.side_effect = [subprocess.CalledProcessError(1, ['go'], output=failed, stderr=''),
                           subprocess.CompletedProcess(['go'], 0, 'complete', '')]
        self.assertEqual(licenses.network_output(['go']), 'complete')
        sleep.assert_called_once_with(2)

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_fatal_stderr_overrides_transient_json_stdout(self, run, sleep):
        error = subprocess.CalledProcessError(1, ['go'], output=json.dumps(dict(Error='i/o timeout')),
                                              stderr='checksum mismatch')
        run.side_effect = error
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            licenses.network_output(['go'])
        self.assertIs(caught.exception, error)
        self.assertIn('checksum mismatch', self.diagnostics.getvalue())
        self.assertIn('i/o timeout', self.diagnostics.getvalue())
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_stdout_fatal_errors_override_transient_stderr_or_json(self, run, sleep):
        for fatal in licenses.FATAL:
            for output in (json.dumps(dict(Error=fatal+'; i/o timeout')),
                           json.dumps(dict(Error='i/o timeout'))+'\n'+json.dumps(dict(Error=fatal)),
                           fatal+'; i/o timeout'):
                with self.subTest(fatal=fatal, output=output):
                    run.reset_mock()
                    error = subprocess.CalledProcessError(1, ['go'], output=output, stderr='connection reset')
                    run.side_effect = error
                    with self.assertRaises(subprocess.CalledProcessError) as caught:
                        licenses.network_output(['go'])
                    self.assertIs(caught.exception, error)
                    self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_unstructured_or_non_error_stdout_never_justifies_retry(self, run, sleep):
        for output in ('i/o timeout', '{"Error": "i/o timeout"',
                       '{"Error": "i/o timeout"}\npartial',
                       json.dumps(dict(Path='example/no such host', Error='unsupported target')),
                       json.dumps(dict(Error=['i/o timeout'])), json.dumps(['i/o timeout']),
                       json.dumps(dict(Error=dict(Detail='i/o timeout'))),
                       '['*2000+'"i/o timeout"'+']'*2000):
            with self.subTest(output=output):
                run.reset_mock()
                error = subprocess.CalledProcessError(1, ['go'], output=output, stderr='')
                run.side_effect = error
                with self.assertRaises(subprocess.CalledProcessError) as caught:
                    licenses.network_output(['go'])
                self.assertIs(caught.exception, error)
                self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_stdout_diagnostics_are_bounded_without_truncating_classification(self, run, sleep):
        limit = licenses.STDOUT_DIAGNOSTIC_LIMIT
        output = 'begin\n'+'a'*limit+'checksum mismatch'+'b'*limit+'\nend'
        error = subprocess.CalledProcessError(1, ['go'], output=output, stderr='i/o timeout')
        run.side_effect = error
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            licenses.network_output(['go'])
        self.assertIs(caught.exception, error)
        self.assertEqual(caught.exception.stdout, output)
        diagnostic = self.diagnostics.getvalue()
        self.assertIn('begin\n', diagnostic)
        self.assertIn('\nend', diagnostic)
        self.assertIn('[stdout truncated]', diagnostic)
        self.assertLess(len(diagnostic), limit+150)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_json_diagnostic_prefers_error_over_large_metadata(self, run, sleep):
        message = 'unsupported target'
        output = json.dumps(dict(Info='a'*(licenses.STDOUT_DIAGNOSTIC_LIMIT*2), Error=message))
        run.side_effect = subprocess.CalledProcessError(1, ['go'], output=output, stderr='')
        with self.assertRaises(subprocess.CalledProcessError): licenses.network_output(['go'])
        self.assertIn(message, self.diagnostics.getvalue())
        self.assertLess(len(self.diagnostics.getvalue()), 100)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_large_json_error_is_bounded_but_classified_in_full(self, run, sleep):
        limit = licenses.STDOUT_DIAGNOSTIC_LIMIT
        message = 'begin\n'+'a'*limit+'checksum mismatch'+'b'*limit+'\nend: i/o timeout'
        output = json.dumps(dict(Error=message))
        error = subprocess.CalledProcessError(1, ['go'], output=output, stderr='')
        run.side_effect = error
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            licenses.network_output(['go'])
        self.assertIs(caught.exception, error)
        self.assertIn('begin\n', self.diagnostics.getvalue())
        self.assertIn('\nend: i/o timeout', self.diagnostics.getvalue())
        self.assertIn('[stdout truncated]', self.diagnostics.getvalue())
        self.assertLess(len(self.diagnostics.getvalue()), limit+150)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    @patch('licenses.time.sleep')
    @patch('licenses.subprocess.run')
    def test_success_returns_untouched_stdout_and_preserves_stderr(self, run, sleep):
        output = json.dumps(dict(Path='example/complete', Dir='/module/cache'))+'\n'
        run.return_value = subprocess.CompletedProcess(['go'], 0, output, 'go: download progress\n')
        self.assertEqual(licenses.network_output(['go']), output)
        self.assertEqual(self.diagnostics.getvalue(), 'go: download progress\n')
        run.assert_called_once()
        sleep.assert_not_called()

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



class ProductionScopeTests(unittest.TestCase):
    @patch('licenses.network_output')
    def test_all_release_targets_including_mobile_cgo_are_inspected(self, output):
        import json
        def graph(command, *, env):
            entry=command[-1]
            return '\n'.join(json.dumps(p) for p in [
                dict(ImportPath='github.com/psportal/psportal/native/'+entry[2:],Module=dict(Main=True)),
                dict(ImportPath=env['GOOS']+'/dep',Module=dict(Path='example/'+env['GOOS'],Version='v1.0.0'))])
        output.side_effect=graph
        required,targets=licenses.production_scope('go')
        self.assertEqual({p for p,v in required}, {'example/'+x for x in ('linux','windows','darwin','android','ios')})
        self.assertEqual(len(targets),10)
        for call in output.call_args_list:
            self.assertEqual(call.args[0][1:5],['list','-deps','-json','-tags'])
            env=call.kwargs['env']
            self.assertEqual(call.args[0][5], licenses.ANDROID_TAGS if env['GOOS']=='android' else licenses.TAGS)
            self.assertEqual(env['CGO_ENABLED'],'1' if env['GOOS'] in ('ios','android') else '0')
            self.assertEqual(call.args[0][-1], './androidmobile' if env['GOOS']=='android' else './mobile' if env['GOOS']=='ios' else './cmd/psportal')

    def test_missing_actual_license_fails_and_graph_only_exclusion_is_explicit(self):
        actual=dict(module='example/runtime',version='v1',licenses=['LICENSE'])
        helper=dict(module='example/helper',version='v2',licenses=[])
        scope=licenses.missing_license_review([actual,helper],{('example/runtime','v1')},[])
        self.assertEqual(scope['excluded_graph_only_missing_notices'][0]['module'],'example/helper')
        with self.assertRaises(RuntimeError):
            licenses.missing_license_review([actual,helper],{('example/helper','v2')},[])
        with self.assertRaises(RuntimeError):
            licenses.missing_license_review([actual],{('example/missing','v1')},[])

    @patch('licenses.network_output')
    def test_incomplete_or_failed_cross_target_graph_never_exempts_missing_modules(self, output):
        import json
        for data in ('', json.dumps(dict(ImportPath='github.com/psportal/psportal/native/cmd/psportal',Incomplete=True))):
            output.return_value=data
            with self.subTest(data=data),self.assertRaises(RuntimeError):licenses.production_scope('go')
        output.side_effect=subprocess.CalledProcessError(1,['go'],stderr='unsupported target')
        with self.assertRaises(subprocess.CalledProcessError):licenses.production_scope('go')


class ReplacementSourceTests(unittest.TestCase):
    def test_local_replacement_preferred_and_original_identity_preserved_in_notices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            original = root / 'upstream'
            replacement = root / 'replacement'
            goroot = root / 'go'
            output = root / 'notices'
            for directory in (original, replacement, goroot):
                directory.mkdir()
            (root / 'LICENSE').write_text('combined application license fixture\n')
            (original / 'LICENSE').write_text('wrong original-only fixture\n')
            (replacement / 'LICENSE').write_text('replacement license fixture\n')
            (replacement / 'NOTICE-PSPORTAL-PATCH.md').write_text('local patch notice fixture\n')
            metadata = replacement / 'PSPORTAL-PATCHES'
            metadata.mkdir()
            provenance = dict(module='github.com/metacubex/mihomo', version='v1.19.32',
                              upstream_go_mod_sum='original-go-mod-sum', upstream_module_sum='original-module-sum')
            (metadata / 'PROVENANCE.json').write_text(json.dumps(provenance))
            (metadata / '0001-atomic-log-level.patch').write_text('exact patch fixture\n')
            module = dict(Path=provenance['module'], Version=provenance['version'], Dir=str(original),
                          Replace=dict(Path='./third_party/mihomo', Dir=str(replacement)))
            with patch.object(licenses, 'ROOT', root), patch.object(licenses, 'network_output', return_value=json.dumps(module)) as network, patch.object(licenses, 'production_scope', return_value=({(module['Path'], module['Version'])}, [])), patch.object(licenses.verify_mihomo_patch, 'verify', return_value=provenance) as verify, patch.object(licenses.subprocess, 'check_output', return_value=str(goroot)), patch('sys.argv', ['licenses.py', '--go', 'verified-go', '--output', str(output)]):
                licenses.main()
            verify.assert_called_once_with(replacement)
            network.assert_called_once_with(['verified-go', 'list', '-m', '-json', 'all'])
            item = json.loads((output / 'MODULES.json').read_text())[0]
            self.assertEqual((item['module'], item['version']), ('github.com/metacubex/mihomo', 'v1.19.32'))
            self.assertEqual(item['replacement']['path'], './third_party/mihomo')
            self.assertEqual(item['replacement']['provenance'], provenance)
            self.assertEqual(item['go_mod'], 'original-go-mod-sum')
            self.assertEqual(item['upstream_sum'], 'original-module-sum')
            combined = (output / 'ENGINE-NOTICES.txt').read_text()
            self.assertIn('replacement license fixture', combined)
            self.assertIn('local patch notice fixture', combined)
            self.assertNotIn('wrong original-only fixture', combined)
            preserved = output / 'github.com_metacubex_mihomo@v1.19.32' / 'PSPORTAL-PATCHES'
            self.assertEqual((preserved / '0001-atomic-log-level.patch').read_text(), 'exact patch fixture\n')

    @patch('licenses.network_output')
    def test_missing_local_replacement_never_downloads_unpatched_upstream(self, network):
        module = dict(Path='github.com/metacubex/mihomo', Version='v1.19.32',
                      Replace=dict(Path='./third_party/mihomo'))
        with self.assertRaisesRegex(RuntimeError, 'Missing local replacement'):
            licenses.module_source('go', module)
        network.assert_not_called()

    @patch('licenses.network_output')
    def test_invalid_local_provenance_fails_before_collecting_notices(self, network):
        with tempfile.TemporaryDirectory() as temporary:
            module = dict(Path='github.com/metacubex/mihomo', Version='v1.19.32',
                          Replace=dict(Path='./third_party/mihomo', Dir=temporary))
            with patch.object(licenses.verify_mihomo_patch, 'verify', side_effect=ValueError('source changed')):
                with self.assertRaisesRegex(ValueError, 'source changed'):
                    licenses.module_source('go', module)
        network.assert_not_called()


if __name__ == '__main__': unittest.main()
