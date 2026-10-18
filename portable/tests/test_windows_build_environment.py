"""No Windows host or child process is needed to check build PATH isolation."""
import os
from pathlib import Path
import tempfile
import unittest

from scripts.windows_build_environment import windows_pyinstaller_environment


class WindowsBuildEnvironmentTests(unittest.TestCase):
    def test_only_selected_python_and_windows_paths_reach_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python, venv, windows, unrelated = [root / name for name in ('python', 'venv', 'Windows', 'JDK')]
            for path in (python, python / 'DLLs', venv / 'Scripts', windows / 'System32', unrelated):
                path.mkdir(parents=True, exist_ok=True)
            executable = venv / 'Scripts' / 'python.exe'
            executable.touch()
            original = {'Path': str(unrelated), 'SystemRoot': str(windows), 'KEEP': 'unchanged'}
            child = windows_pyinstaller_environment(original, executable=str(executable),
                prefix=str(venv), base_prefix=str(python))
            self.assertEqual(original, {'Path': str(unrelated), 'SystemRoot': str(windows), 'KEEP': 'unchanged'})
            self.assertEqual(child['KEEP'], 'unchanged')
            self.assertNotIn('Path', child)
            self.assertEqual(child['PATH'].split(os.pathsep), [str(venv / 'Scripts'), str(venv),
                str(python), str(python / 'DLLs'), str(windows / 'System32'), str(windows)])

    def test_missing_or_relative_required_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'System32').mkdir()
            executable = root / 'python.exe'
            executable.touch()
            good = dict(executable=str(executable), prefix=str(root), base_prefix=str(root))
            for environment in ({}, {'SystemRoot': 'relative'}, {'SystemRoot': str(root / 'missing')}):
                with self.subTest(environment=environment), self.assertRaises(ValueError):
                    windows_pyinstaller_environment(environment, **good)
            for key in good:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    windows_pyinstaller_environment({'SystemRoot': str(root)}, **dict(good, **{key: 'relative'}))

    def test_case_insensitive_environment_and_duplicate_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'System32').mkdir()
            executable = root / 'python.exe'
            executable.touch()
            child = windows_pyinstaller_environment({'WINDIR': str(root), 'PATH': 'discard', 'pAtH': 'discard'},
                executable=str(executable), prefix=str(root), base_prefix=str(root))
            self.assertEqual(child['PATH'].split(os.pathsep), [str(root), str(root / 'System32')])
            self.assertNotIn('pAtH', child)
