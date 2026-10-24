import io
import tarfile
import unittest
from pathlib import Path, PurePosixPath


class OpenWrtPackage(unittest.TestCase):
    def test_linux_paths_parents_modes_and_no_account_payload(self):
        package = Path(__file__).resolve().parents[1] / 'xianniu-router_0.4.4_all.ipk'
        with tarfile.open(package) as outer:
            self.assertEqual(outer.extractfile('./debian-binary').read(), b'2.0\n')
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile('./data.tar.gz').read())) as archive:
                members = archive.getmembers()
                self.assertTrue(all('\\' not in member.name for member in members))
                directories = {PurePosixPath(m.name) for m in members if m.isdir()}
                names = {m.name for m in members}
                self.assertNotIn('./etc/xianniu-router/session.json', names)
                for member in members:
                    if member.isfile():
                        self.assertIn(PurePosixPath(member.name).parent, directories)
                self.assertEqual(archive.getmember('./usr/bin/xianniu-router').mode, 0o755)
                self.assertIn('./usr/lib/xianniu-router/xianniu_router/__main__.py', names)
                self.assertIn('./usr/lib/xianniu-router/starpass_http/proxy.py', names)
                self.assertIn('./usr/share/xianniu-router/LICENSE-StarPass', names)
                self.assertEqual(archive.getmember('./usr/libexec/rpcd/xianniu').mode, 0o755)


if __name__ == '__main__':
    unittest.main()
