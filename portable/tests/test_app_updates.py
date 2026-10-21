import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
from portalproxy import app_updates as u


def release(version='0.2.0', os_name='Linux', arch='x64', **kw):
    ext = 'zip' if os_name == 'Windows' else 'tar.gz'
    name = f'StarPass-Desktop-{version}-{os_name}-{arch}.{ext}'
    obj = {'draft': False, 'prerelease': False, 'tag_name': 'v'+version, 'body': 'Notes', 'assets': [{
        'name': name, 'state': 'uploaded', 'size': 7, 'digest': 'sha256:' + hashlib.sha256(b'package').hexdigest(),
        'browser_download_url': f'https://github.com/{u.REPOSITORY}/releases/download/v{version}/{name}'}]}
    obj.update(kw)
    return obj


class SelectionTests(unittest.TestCase):
    def select(self, data, current='0.1.0', system='Linux', machine='x86_64'):
        return u.select_update(data, current, system, machine)

    def test_independent_platform_version_not_release_tag(self):
        android = release(); android['assets'][0]['name'] = 'StarPass-Android-99-universal.apk'
        candidate, published = self.select([release('80.0.0', 'Windows'), android, release()])
        self.assertEqual(candidate.version, (0, 2, 0)); self.assertTrue(published)

    def test_numeric_sort_and_unordered_history(self):
        self.assertEqual(self.select([release('0.9.0'), release('0.10.0'), release('0.3.0')])[0].version, (0,10,0))

    def test_draft_prerelease_and_old_archives_excluded(self):
        self.assertEqual(self.select([release(draft=True), release(prerelease=True), {'assets': []}]), (None, False))

    def test_same_or_lower_version_never_updates(self):
        self.assertEqual(self.select([release()], '0.2.0'), (None, True))
        self.assertEqual(self.select([release()], '1.0.0'), (None, True))

    def test_no_assets_is_not_up_to_date(self):
        self.assertEqual(self.select([]), (None, False))

    def test_macos_native_before_universal(self):
        candidate, _ = self.select([release('0.2.0','macOS','universal'), release('0.2.0','macOS','arm64')], system='Darwin', machine='arm64')
        self.assertIn('-arm64.', candidate.name)
        candidate, _ = self.select([release('0.3.0','macOS','universal'),release('0.2.0','macOS','arm64')],system='Darwin',machine='arm64')
        self.assertIn('-universal.', candidate.name)

    def test_all_platform_targets(self):
        for system, os_name in [('Windows','Windows'),('Darwin','macOS'),('Linux','Linux')]:
            for machine, arch in [('AMD64','x64'),('x86_64','x64'),('aarch64','arm64'),('arm64','arm64')]:
                with self.subTest(system=system,machine=machine):
                    self.assertIsNotNone(self.select([release(os_name=os_name,arch=arch)],system=system,machine=machine)[0])

    def test_wrong_architecture(self):
        self.assertEqual(self.select([release(arch='arm64')]),(None,False))

    def test_unknown_architecture_fails(self):
        with self.assertRaises(u.UpdateError): self.select([],machine='riscv64')

    def test_missing_digest_fails_closed(self):
        r=release(); del r['assets'][0]['digest']
        with self.assertRaises(u.UpdateError): self.select([r])

    def test_bad_size_and_digest(self):
        for field, value in [('size',True),('size',0),('size',u.MAX_PACKAGE+1),('digest','sha1:123'),('size','7')]:
            r=release();r['assets'][0][field]=value
            with self.subTest(field=field,value=value), self.assertRaises(u.UpdateError): self.select([r])

    def test_wrong_filename_url(self):
        r=release();r['assets'][0]['browser_download_url'] += '.evil'
        with self.assertRaises(u.UpdateError): self.select([r])

    def test_conflicting_same_version_rejected(self):
        a=release();b=release();b['assets'][0]['digest']='sha256:'+'0'*64
        with self.assertRaises(u.UpdateError): self.select([a,b])

    def test_bad_metadata(self):
        for value in [{}, None, [release()]*101]:
            with self.subTest(value=type(value)),self.assertRaises(u.UpdateError): self.select(value)

    def test_version_format(self):
        for value in ['0.2','01.2.3','v1.2.3','1.2.3-dev','1.2.3.4']:
            with self.subTest(value=value),self.assertRaises(u.UpdateError): self.select([],value)

    def test_unfinished_asset_ignored(self):
        r=release();r['assets'][0]['state']='new'
        self.assertEqual(self.select([r]),(None,False))

    def test_wrong_release_tag_rejected(self):
        r=release();r['tag_name']='other-release'
        with self.assertRaises(u.UpdateError):self.select([r])

    def test_oversize_version_ignored(self):
        self.assertEqual(self.select([release('9999999999.0.0')]),(None,False))

    def test_notes_bounded(self):
        self.assertEqual(len(self.select([release(body='n'*10000)])[0].notes),4000)

    def test_url_restrictions(self):
        good=release()['assets'][0]['browser_download_url'];self.assertTrue(u.trusted_url(good))
        for url in ['http://github.com/a','https://evil.com/'+good,'https://github.com.evil.com/a',good+'?redirect=evil',good+'#fragment',good.replace('github.com','u:p@github.com'),good.replace(u.REPOSITORY,'someone/else'),good.replace('/v0.2.0/','/../'),good.replace('/v0.2.0/','/%2e%2e/'),'https://github.com:444/'+u.REPOSITORY+'/releases/download/v/a']:
            with self.subTest(url=url): self.assertFalse(u.trusted_url(url))
        self.assertFalse(u.trusted_url('https://release-assets.githubusercontent.com/file'))
        self.assertTrue(u.trusted_url('https://release-assets.githubusercontent.com/file?sig=x',redirect=True))

    def test_redirect_blocked_before_follow(self):
        req=urllib.request.Request(release()['assets'][0]['browser_download_url'])
        with self.assertRaises(u.UpdateError): u.SafeRedirect().redirect_request(req,None,302,'',{},'http://evil.com')


class Response(io.BytesIO):
    def __init__(self,data,url,headers=None):
        super().__init__(data);self.url=url;self.headers=headers or {}
    def geturl(self): return self.url


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'package.tar.gz'
        self.update=u.select_update([release()],'0.1.0','Linux','x86_64')[0]
        self.cancel=threading.Event()

    def fetch(self,data=b'package',headers=None,url=None):
        fake=unittest.mock.Mock();fake.open.return_value=Response(data,url or self.update.url,headers)
        return patch.object(u,'opener',return_value=fake)

    def test_verified_atomic_download(self):
        progress=[]
        with self.fetch(headers={'Content-Length':'7'}):
            self.assertEqual(u.download(self.update,self.path,self.cancel,lambda n,t:progress.append((n,t))),self.path)
        self.assertEqual(self.path.read_bytes(),b'package');self.assertEqual(progress,[(7,7)])
        self.assertEqual(len(list(self.path.parent.iterdir())),1)

    def test_no_overwrite_existing_config_or_package(self):
        self.path.write_bytes(b'original configuration')
        with self.fetch(),self.assertRaises(FileExistsError):u.download(self.update,self.path,self.cancel)
        self.assertEqual(self.path.read_bytes(),b'original configuration')
        self.assertEqual(len(list(self.path.parent.iterdir())),1)

    def test_bad_hash_short_overlong_no_partial_files(self):
        for data in [b'badpack',b'pack',b'package-extra']:
            with self.subTest(data=data),self.fetch(data),self.assertRaises(u.UpdateError):u.download(self.update,self.path,self.cancel)
            self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_bad_length_header(self):
        for length in ['8','-1','text']:
            with self.subTest(length=length),self.fetch(headers={'Content-Length':length}),self.assertRaises(u.UpdateError):u.download(self.update,self.path,self.cancel)
            self.assertFalse(self.path.exists())

    def test_cancel_before_and_after_read(self):
        self.cancel.set()
        with self.fetch(),self.assertRaises(u.UpdateError):u.download(self.update,self.path,self.cancel)
        self.cancel.clear()
        with self.fetch(),self.assertRaises(u.UpdateError):u.download(self.update,self.path,self.cancel,lambda *_:self.cancel.set())
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_disk_publish_failure_keeps_original_and_cleans_temp(self):
        with self.fetch(),patch.object(u.os,'link',side_effect=OSError('disk')),self.assertRaises(OSError):u.download(self.update,self.path,self.cancel)
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_network_failure(self):
        fake=unittest.mock.Mock();fake.open.side_effect=OSError('offline')
        with patch.object(u,'opener',return_value=fake),self.assertRaises(OSError):u.download(self.update,self.path,self.cancel)
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_response_destination_rejected(self):
        with self.fetch(url='https://evil.com/package'),self.assertRaises(u.UpdateError):u.download(self.update,self.path,self.cancel)
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_download_time_budget(self):
        with self.fetch(),patch.object(u.time,'monotonic',side_effect=[0,u.MAX_DOWNLOAD_SECONDS+1]),self.assertRaises(u.UpdateError):
            u.download(self.update,self.path,self.cancel)
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_stream_uses_single_read_chunks_for_deadline(self):
        class Trickle(Response):
            def read(self,*args):raise AssertionError('read can block across repeated socket receives')
            def read1(self,size):return super().read1(min(size,1))
        fake=unittest.mock.Mock();fake.open.return_value=Trickle(b'package',self.update.url)
        with patch.object(u,'opener',return_value=fake):u.download(self.update,self.path,self.cancel)
        self.assertEqual(self.path.read_bytes(),b'package')

    def test_download_revalidates_metadata(self):
        from dataclasses import replace
        for change in [{'size':0},{'size':u.MAX_PACKAGE+1},{'sha256':'bad'},{'url':'http://example.com'}]:
            with self.subTest(change=change),self.assertRaises(u.UpdateError):
                u.download(replace(self.update,**change),self.path,self.cancel)
        self.assertEqual(list(self.path.parent.iterdir()),[])

    def test_metadata_check_network_and_bounds(self):
        fake=unittest.mock.Mock();fake.open.return_value=Response(json.dumps([release()]).encode(),u.RELEASES_URL)
        with patch.object(u,'opener',return_value=fake):self.assertIsNotNone(u.check('0.1.0','Linux','x86_64')[0])
        fake.open.return_value=Response(b'x'*(u.MAX_METADATA+1),u.RELEASES_URL)
        with patch.object(u,'opener',return_value=fake),self.assertRaises(u.UpdateError):u.check('0.1.0','Linux','x86_64')
        fake.open.side_effect=OSError('offline')
        with patch.object(u,'opener',return_value=fake),self.assertRaises(OSError):u.check('0.1.0','Linux','x86_64')


if __name__=='__main__':unittest.main()
