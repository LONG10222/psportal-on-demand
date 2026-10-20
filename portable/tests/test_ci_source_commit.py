"""Evidence uses the immutable SHA also supplied to checkout, not a merge ref."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ci_build_dual', Path(__file__).resolve().parents[1] / 'ci/build_dual.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class BuildCommitTests(unittest.TestCase):
    def test_exact_checkout_head_precedes_synthetic_event_merge(self):
        with patch.dict(os.environ, {'PSPORTAL_SOURCE_COMMIT': 'a'*40, 'GITHUB_SHA': 'b'*40}, clear=True):
            self.assertEqual(ci.source_commit(), 'a'*40)
        with patch.dict(os.environ, {'GITHUB_SHA': 'b'*40}, clear=True):
            self.assertEqual(ci.source_commit(), 'b'*40)

    def test_mutable_or_malformed_identity_is_not_accepted(self):
        for value in ('main', 'abc123', 'g'*40, '../other', 'a'*40+'\n'):
            with self.subTest(value=value), patch.dict(os.environ, {'PSPORTAL_SOURCE_COMMIT': value}, clear=True):
                with self.assertRaises(ValueError): ci.source_commit()
