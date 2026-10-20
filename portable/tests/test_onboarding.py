"""Beginner checks stay local and secret-free."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from portalproxy import onboarding, i18n
from portalproxy.desktop import DesktopApp
from portalproxy.desktop_view import core_readiness_note


class CoreReadinessNoteTests(unittest.TestCase):
    def test_missing_external_core_is_honest_about_platform_support(self):
        for platform, machine, automatic in (
                ('win32', 'AMD64', True), ('win32', 'ARM64', False),
                ('darwin', 'arm64', False), ('linux', 'x86_64', False)):
            with self.subTest(platform=platform, machine=machine), \
                    patch('portalproxy.core_setup.sys.platform', platform), \
                    patch('portalproxy.core_setup.platform.machine', return_value=machine):
                note = core_readiness_note('external', '')
                if automatic:
                    self.assertEqual(note, 'The default core will be prepared when you click Start sharing.')
                else:
                    self.assertEqual(note, 'Choose your verified Mihomo executable in Advanced settings, or reuse an existing Clash client.')
                self.assertNotEqual(i18n.text(note, 'zh'), note)

    def test_embedded_never_promises_default_mihomo_or_automatic_download(self):
        for platform in ('win32', 'darwin', 'linux'):
            with self.subTest(platform=platform), \
                    patch('portalproxy.core_setup.sys.platform', platform), \
                    patch('portalproxy.core_setup.platform.machine', return_value='AMD64'):
                note = core_readiness_note('embedded', '')
                self.assertEqual(note, 'Select a matching native engine in Advanced settings, or switch to external Mihomo.')
                self.assertNotEqual(i18n.text(note, 'zh'), note)

    def test_existing_custom_core_is_not_called_default_or_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = Path(tmp) / 'user-selected-core'
            core.write_bytes(b'not executable')
            for engine, expected in (
                    ('external', 'Selected Mihomo core is available.'),
                    ('embedded', 'Experimental embedded engine is available.')):
                with self.subTest(engine=engine), \
                        patch('portalproxy.core_setup.can_install', side_effect=AssertionError('not needed')):
                    note = core_readiness_note(engine, str(core))
                    self.assertEqual(note, expected)
                    self.assertNotEqual(i18n.text(note, 'zh'), note)

class OnboardingTests(unittest.TestCase):
    def test_preparation_and_first_step_match_supported_platform_setup(self):
        for platform, machine, automatic in (
                ('win32', 'AMD64', True), ('win32', 'ARM64', False),
                ('darwin', 'arm64', False), ('linux', 'x86_64', False)):
            with self.subTest(platform=platform, machine=machine), \
                    patch('portalproxy.core_setup.sys.platform', platform), \
                    patch('portalproxy.core_setup.platform.machine', return_value=machine):
                preparation = onboarding.preparation_notes({})[-1]
                first_step = onboarding.next_step('clash', False, 0)
                if automatic:
                    self.assertIn('Start sharing prepares a missing default core', preparation)
                    self.assertIn('prepared automatically', first_step)
                else:
                    self.assertIn('Select your trusted Mihomo executable', preparation)
                    self.assertIn('does not download a core automatically', preparation)
                    self.assertIn('needs a trusted core', first_step)
                    self.assertNotIn('prepared automatically', first_step)
                embedded = onboarding.preparation_notes({'engine_mode': 'embedded'})[-1]
                self.assertEqual(embedded, 'Select a matching native engine in Advanced settings, or switch to external Mihomo.')
                for text in (preparation, first_step, embedded):
                    self.assertNotEqual(i18n.text(text, 'zh'), text)

    def test_empty_first_launch(self):
        notes=onboarding.preparation_notes({})
        self.assertEqual(len(notes),2)
        self.assertIn('HTTPS subscription',notes[0])
        self.assertIn('Share existing Clash',notes[1])
    def test_existing_client_needs_no_separate_core_or_source(self):
        notes = onboarding.preparation_notes({'existing_proxy_port': 7890})
        self.assertEqual(len(notes), 1)
        self.assertIn('does not need', notes[0])
        self.assertIn('verify access', notes[0])
    def test_url_validation_and_redaction(self):
        for url in ('https://a.example:999999/private?token=secret','http://a.example/private','https://user:secret@a.example','https://a.example/#secret','https://a.example/\nsecret'):
            self.assertFalse(onboarding.source_ready({'subscription_url':url}))
            self.assertNotIn('secret',' '.join(onboarding.preparation_notes({'subscription_url':url})))
        self.assertTrue(onboarding.source_ready({'subscription_url':'https://example.com/path?token=secret'}))
    def test_files_not_executed_or_claimed_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            core=Path(tmp)/'core';core.write_text('not executable')
            profile=Path(tmp)/'profile';profile.write_text('not parsed')
            values={'core_path':str(core),'profile_file':str(profile)}
            notes=onboarding.preparation_notes(values)
            self.assertEqual(len(notes),1);self.assertIn('not verified',notes[0])
            values['engine_mode']='embedded';self.assertFalse(onboarding.engine_ready(values))
            values['native_path']=str(core);self.assertTrue(onboarding.engine_ready(values))
    def test_connection_is_not_verified_exit(self):
        self.assertTrue(onboarding.next_step('game',False,5).startswith('1.'))
        self.assertTrue(onboarding.next_step('game',True,0).startswith('2.'))
        self.assertIn('127.0.0.1',onboarding.next_step('clash',True,0))
        self.assertIn('not proof',onboarding.next_step('game',True,1))
        self.assertIn('errors',onboarding.next_step('game',True,1,2))
        self.assertTrue(onboarding.next_step('game',True,'unknown').startswith('2.'))
    def test_no_lifecycle_side_effects(self):
        app=object.__new__(DesktopApp);app.root=object();app.vars={};app.raw={}
        app._t=lambda key:i18n.text(key,'zh');app.start=Mock();app.import_subscription=Mock()
        with patch('tkinter.messagebox.showinfo') as shown,patch('socket.create_connection',side_effect=AssertionError('network')):
            app.check_preparation()
        app.start.assert_not_called();app.import_subscription.assert_not_called()
        self.assertIn('首次使用',shown.call_args.args[1]);self.assertEqual(shown.call_args.args[0],'使用前检查')
