"""Display/network-free checks for the diagnostic runtime inventory tool."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'inventory_desktop_runtime.py'
spec = importlib.util.spec_from_file_location('desktop_runtime_inventory', SCRIPT)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class RuntimeInventoryTests(unittest.TestCase):
    def test_pe_version_strings_preserve_origin_and_version_without_license_claim(self):
        fixed = SimpleNamespace(FileVersionMS=(14 << 16) + 44, FileVersionLS=(35211 << 16),
                                ProductVersionMS=(14 << 16) + 44, ProductVersionLS=(35211 << 16))
        table = SimpleNamespace(LangID=b'040904b0', entries={b'OriginalFilename': b'VCRUNTIME140.dll',
            b'CompanyName': b'Microsoft Corporation'})
        pe = SimpleNamespace(VS_FIXEDFILEINFO=[fixed], FileInfo=[[SimpleNamespace(StringTable=[table])]])
        metadata = inventory.pe_version_metadata(pe)
        self.assertEqual(metadata['file_version'], '14.44.35211.0')
        self.assertEqual(metadata['string_tables'][0]['entries']['OriginalFilename'], 'VCRUNTIME140.dll')
        self.assertEqual(inventory.pe_version_metadata(SimpleNamespace()), {'string_tables': []})

    def test_api_set_proof_never_loads_arbitrary_names_or_paths(self):
        for name in ('kernel32.dll', 'untrusted.dll', '../api-ms-win-core-path-l1-1-0.dll',
                     'C:\\api-ms-win-core-path-l1-1-0.dll', 'api-ms-win-core-path-l1-1-0.dll/extra'):
            with self.subTest(name=name):
                self.assertIsNone(inventory.windows_api_set_resolution(name))

    @unittest.skipUnless(sys.platform == 'win32', 'actual Windows API-set loader proof')
    def test_windows_api_set_has_exact_system_host_evidence(self):
        proof = inventory.windows_api_set_resolution('api-ms-win-core-path-l1-1-0.dll')
        self.assertIsNotNone(proof)
        self.assertEqual(proof['resolution_method'], 'windows-api-set-system-loader')
        host = Path(proof['resolved'])
        self.assertTrue(host.is_file())
        self.assertEqual(host.parent.name.casefold(), 'system32')
        self.assertEqual(proof['system_sha256'], inventory.digest(host))

    def test_toc_walk_collects_only_known_data_records(self):
        values = ([('libpython.so', '/installed/libpython.so', 'BINARY'),
                   [('module', '/installed/module.py', 'PYMODULE')]],
                  ['not', 'a', 'record'], ['name', 3, 'DATA'])
        self.assertEqual(list(inventory.toc_entries(values)), [
            ('libpython.so', '/installed/libpython.so', 'BINARY'),
            ('module', '/installed/module.py', 'PYMODULE')])

    def test_known_bundle_layouts_preserve_exact_destination(self):
        for prefix in ('_internal/', 'Contents/Frameworks/', 'Contents/Resources/', 'Contents/MacOS/'):
            with self.subTest(prefix=prefix):
                self.assertEqual(inventory.destination_keys(prefix + 'Python.framework/Python'),
                    {prefix + 'Python.framework/Python', 'Python.framework/Python'})
        self.assertEqual(inventory.destination_keys('_internal\\python313.dll'),
            {'_internal/python313.dll', 'python313.dll'})

    def test_license_names_include_component_prefixed_notices(self):
        for name in ('LICENSE', 'LICENSE.txt', 'license.terms', 'COPYING',
                     'Python-LICENSE.txt', 'libtcl8.6.copyright', 'THIRD-PARTY-NOTICES.md'):
            with self.subTest(name=name):
                self.assertIsNotNone(inventory.LICENSE_NAME.search(name))
        for name in ('unlicensed.py', 'config.json'):
            with self.subTest(name=name):
                self.assertIsNone(inventory.LICENSE_NAME.search(name))

    def test_component_labels_are_only_path_hints(self):
        self.assertEqual(inventory.component('C:\\Python\\tcl\\tcl8.6\\license.terms'), 'Tcl')
        self.assertEqual(inventory.component('/Python/Tk.framework/Versions/8.6/Resources/license.terms'), 'Tk')
        self.assertEqual(inventory.component('/Python/lib/python3.13/_tkinter.so'), 'other-runtime')

    def test_file_magic_and_exact_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'component'
            for contents, expected in ((b'\x7fELFpayload', 'ELF'), (b'MZpayload', 'PE'),
                                       (b'\xcf\xfa\xed\xfepayload', 'Mach-O'), (b'text', None)):
                path.write_bytes(contents)
                self.assertEqual(inventory.binary_format(path), expected)
                self.assertEqual(inventory.digest(path), inventory.hashlib.sha256(contents).hexdigest())

    def test_output_cannot_modify_bundle_or_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, build = Path(tmp) / 'app', Path(tmp) / 'build'
            app.mkdir(); build.mkdir()
            for output in (app, app / 'diagnostic', build / 'diagnostic'):
                with self.subTest(output=output), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        inventory.main(['--app', str(app), '--build', str(build), '--output', str(output)])
                    self.assertEqual(error.exception.code, 2)
            self.assertEqual(list(app.iterdir()), [])
            self.assertEqual(list(build.iterdir()), [])

    def test_output_does_not_overwrite_previous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('app', 'build', 'output'):
                (root / name).mkdir()
            sentinel = root / 'output' / 'existing.json'
            sentinel.write_text('previous evidence')
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                inventory.main(['--app', str(root / 'app'), '--build', str(root / 'build'),
                                '--output', str(root / 'output')])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(sentinel.read_text(), 'previous evidence')
