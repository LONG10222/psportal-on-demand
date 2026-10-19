import asyncio
import ctypes
from types import SimpleNamespace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, call, patch
from portalproxy.process_env import external_environment, launch_external


class EnvironmentTests(unittest.TestCase):
    def test_source_environment_is_unchanged(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(external_environment(), dict(os.environ))

    def test_frozen_linux_restores_original_library_path_without_mutating_parent(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'), patch.dict(os.environ, {'LD_LIBRARY_PATH': '/bundle:/original', 'LD_LIBRARY_PATH_ORIG': '/original'}):
            child = external_environment()
            self.assertEqual(child['LD_LIBRARY_PATH'], '/original')
            self.assertNotIn('LD_LIBRARY_PATH_ORIG', child)
            self.assertEqual(os.environ['LD_LIBRARY_PATH'], '/bundle:/original')

    def test_frozen_linux_clears_override_without_original(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'), patch.dict(os.environ, {'LD_LIBRARY_PATH': '/bundle'}, clear=True):
            self.assertNotIn('LD_LIBRARY_PATH', external_environment())

    def test_frozen_path_removes_only_bundle_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp) / 'bundle')
            sibling = str(Path(tmp) / 'bundle-other')
            path = os.pathsep.join([root, str(Path(root) / 'bin'), sibling, '/usr/bin'])
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', root, create=True), patch.dict(os.environ, {'PATH': path}):
                self.assertEqual(external_environment()['PATH'], os.pathsep.join([sibling, '/usr/bin']))


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    async def test_launch_uses_array_and_sanitized_environment(self):
        fake = AsyncMock(return_value='child')
        with patch('asyncio.create_subprocess_exec', fake), patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(await launch_external('/path with spaces/mihomo', '-t', cwd='/private session'), 'child')
        self.assertEqual(fake.call_args.args, ('/path with spaces/mihomo', '-t'))
        self.assertNotIn('shell', fake.call_args.kwargs)
        self.assertEqual(fake.call_args.kwargs['cwd'], '/private session')
        self.assertEqual(fake.call_args.kwargs['stdout'], asyncio.subprocess.DEVNULL)


class WindowsLaunchContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_frozen_clears_then_restores_dll_directory(self):
        setter = Mock(return_value=1)
        dll = SimpleNamespace(kernel32=SimpleNamespace(SetDllDirectoryW=setter))
        fake = AsyncMock(return_value='child')
        with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', '/bundle', create=True), patch.object(ctypes, 'windll', dll, create=True), patch('subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), patch('asyncio.create_subprocess_exec', fake):
            self.assertEqual(await launch_external('mihomo.exe', '-t'), 'child')
        self.assertEqual(setter.call_args_list, [call(None), call('/bundle')])
        self.assertEqual(fake.call_args.kwargs['creationflags'], 0x08000000)

    async def test_windows_frozen_restores_after_spawn_error(self):
        setter = Mock(return_value=1)
        dll = SimpleNamespace(kernel32=SimpleNamespace(SetDllDirectoryW=setter))
        with patch.object(sys, 'platform', 'win32'), patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', '/bundle', create=True), patch.object(ctypes, 'windll', dll, create=True), patch('subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), patch('asyncio.create_subprocess_exec', AsyncMock(side_effect=OSError)):
            with self.assertRaises(OSError):
                await launch_external('mihomo.exe', '-t')
        self.assertEqual(setter.call_args_list, [call(None), call('/bundle')])
