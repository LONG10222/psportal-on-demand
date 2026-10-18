"""Scratch-only strict transformation checks; never execute inspected binaries."""
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import unittest

from scripts.macho_origin_proof import byte_difference_summary, file_hash, prove_macho_origin, target_rpath


class MachOOriginProofTests(unittest.TestCase):
    def test_rpath_matches_pinned_pyinstaller_directory_depth(self):
        self.assertEqual(target_rpath('Tcl'), '@loader_path')
        self.assertEqual(target_rpath('python3__dot__13/lib-dynload/_struct.so'), '@loader_path/../..')
        self.assertEqual(target_rpath('Python.framework/Versions/3.13/Python'), '@loader_path/../../..')
        for path in ('/absolute', '../escape', 'directory/../escape', ''):
            with self.subTest(path=path), self.assertRaises(ValueError):
                target_rpath(path)

    def test_difference_diagnostics_are_bounded_without_ignoring_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            left, right = Path(temporary) / 'a', Path(temporary) / 'b'
            left.write_bytes(bytes(100))
            right.write_bytes(bytes([1]) * 101)
            report = byte_difference_summary(left, right)
            self.assertEqual(report['differing_bytes_in_common_length'], 100)
            self.assertEqual(report['first_differing_offsets'], list(range(32)))
            self.assertEqual(report['trailing_size_difference'], 1)

    @unittest.skipUnless(sys.platform != 'darwin', 'non-macOS fail-closed check')
    def test_other_platforms_never_claim_a_transformation_proof(self):
        result = prove_macho_origin('/absent/source', '/absent/package', 'file', 'BINARY')
        self.assertFalse(result['verified'])
        self.assertEqual(result['commands'], [])

    @unittest.skipUnless(sys.platform == 'darwin', 'actual macOS normalization tools')
    def test_real_scratch_normalization_matches_and_detects_modified_code(self):
        import _struct
        import unicodedata
        from macholib.MachO import MachO
        from PyInstaller.utils import osx
        from PyInstaller.utils.hooks.tcl_tk import tcltk_info
        sources = [
            (Path(_struct.__file__), 'python3__dot__13/lib-dynload/' + Path(_struct.__file__).name, 'EXTENSION'),
            (Path(unicodedata.__file__), 'python3__dot__13/lib-dynload/' + Path(unicodedata.__file__).name, 'EXTENSION'),
            (Path(sys.base_prefix) / 'Python', 'Python.framework/Versions/3.13/Python', 'BINARY'),
            (Path(sys.base_prefix) / 'lib/libcrypto.3.dylib', 'libcrypto.3.dylib', 'BINARY'),
            (Path(tcltk_info.tcl_shared_library), 'Tcl', 'BINARY'),
            (Path(tcltk_info.tk_shared_library), 'Tk', 'BINARY'),
        ]
        for source, destination, kind in sources:
            with self.subTest(source=str(source)):
                self.assertTrue(source.is_file(), source)
                before = file_hash(source)
                with tempfile.TemporaryDirectory(prefix='psportal-proof-test-') as temporary:
                    packaged = Path(temporary) / source.name
                    shutil.copyfile(source, packaged)
                    osx.binary_to_target_arch(str(packaged), platform.machine())
                    osx.set_dylib_dependency_paths(str(packaged), target_rpath(destination))
                    osx.sign_binary(str(packaged))
                    packed_before = file_hash(packaged)
                    proof = prove_macho_origin(source, packaged, destination, kind)
                    self.assertTrue(proof['verified'], proof)
                    self.assertEqual(file_hash(source), before)
                    self.assertEqual(file_hash(packaged), packed_before)
                    offset = next(section.offset for _, _, sections in MachO(str(packaged)).headers[0].commands
                                  if isinstance(sections, list) for section in sections
                                  if section.sectname.rstrip(b'\0') == b'__text' and section.size > 0)
                    with packaged.open('r+b') as stream:
                        stream.seek(offset)
                        byte = stream.read(1)
                        stream.seek(offset)
                        stream.write(bytes([byte[0] ^ 1]))
                    changed = file_hash(packaged)
                    proof = prove_macho_origin(source, packaged, destination, kind)
                    self.assertFalse(proof['verified'], proof)
                    self.assertEqual(file_hash(source), before)
                    self.assertEqual(file_hash(packaged), changed)
