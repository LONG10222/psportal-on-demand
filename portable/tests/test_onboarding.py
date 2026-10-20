"""Beginner checks stay local and secret-free."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from portalproxy import onboarding, i18n
from portalproxy.desktop import DesktopApp

class OnboardingTests(unittest.TestCase):
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
