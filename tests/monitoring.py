"""Real proxy byte accounting and bounded, configuration-preserving updates."""
import asyncio,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'gateway'),str(ROOT/'integrations/xianniu-router/src')]
import entry,monitor,updater,metrics
from starpass_http.policy import Route

class Traffic(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_lan_and_public_counts_are_separate(self):
        payload=b'x'*8192
        async def echo(reader,writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 8192\r\n\r\n'+payload);await writer.drain();writer.close()
        backend=await asyncio.start_server(echo,'127.0.0.1',0)
        address=backend.sockets[0].getsockname()
        class Core:
            async def acquire_for_request(self,*args):return address
            async def release(self):pass
            async def open_connection(self,*args):return await asyncio.open_connection(*address)
        async def resolve(host,port):
            kind='local' if host=='192.168.50.1' else 'external'
            proxy.set_destination(kind)
            return Route(kind,'127.0.0.1' if kind=='local' else None)
        proxy=metrics.MeteredProxy({'listen_host':'127.0.0.1','listen_port':0,'allowed_clients':['127.0.0.1'],'destination_resolver':resolve},Core())
        await proxy.start()
        async def client(host):
            r,w=await asyncio.open_connection(*proxy.bound_addresses[0][:2])
            req=('GET http://'+host+':'+str(address[1])+'/ HTTP/1.1\r\nHost: '+host+':'+str(address[1])+'\r\n\r\n').encode()
            w.write(req);await w.drain();response=await r.read();w.close();await w.wait_closed()
            self.assertTrue(response.endswith(payload),response[:300]);return len(req),len(response)
        try:
            results=await asyncio.gather(client('192.168.50.1'),client('example.com'))
            for kind,counts in zip(('local','external'),results):self.assertEqual(proxy.meter.bytes[kind],dict(zip(('upload','download'),counts)))
            snapshot=proxy.meter.sample();self.assertGreater(snapshot['uptime'],0)
            self.assertNotIn('example.com',json.dumps(snapshot))
        finally:await proxy.close();backend.close();await backend.wait_closed()
    def test_idle_rates_return_to_zero_and_counters_do_not_reset(self):
        with patch('metrics.time.monotonic',side_effect=[0,1,2]):
            m=metrics.Meter();m.add('external','download',100)
            self.assertEqual(m.sample()['speed']['external']['download'],100)
            self.assertEqual(m.sample()['speed']['external']['download'],0)
            self.assertEqual(m.bytes['external']['download'],100)

class Subscription(unittest.TestCase):
    def test_partial_unknown_and_zero_fields(self):
        self.assertEqual(monitor.userinfo('upload=10; download=20; total=0; expire=0'),{'upload':10,'download':20,'total':0,'expire':0})
        self.assertEqual(monitor.userinfo('upload=-1;total=NaN;expire=9007199254740992;garbage=x'),{})
        self.assertEqual(monitor.userinfo(None),{})
    def test_snapshot_never_returns_subscription_url(self):
        row={'id':'fingerprint','title':'Provider','game':True,'starpass':True,'url':'https://secret.example/token','agent':'a'}
        with patch('monitor.sources',return_value=[row]),patch('monitor.read_json',return_value={}),patch('updater.status',return_value={}):
            value=monitor.snapshot()
        self.assertNotIn('secret.example',json.dumps(value));self.assertNotIn('fingerprint',json.dumps(value))
    def test_failed_refresh_retains_last_good_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cache.json';path.write_text(json.dumps({'id':{'info':{'total':100},'updated_at':123}}))
            with patch('monitor.CACHE',path),patch('monitor.sources',return_value=[{'id':'id','url':'https://provider.example/s','agent':'a'}]),patch('monitor.request',side_effect=OSError()):
                monitor.refresh();cached=json.loads(path.read_text())['id']
            self.assertEqual(cached['info']['total'],100);self.assertEqual(cached['state'],'error');self.assertEqual(cached['updated_at'],123)

class Updates(unittest.TestCase):
    def release(self,v='0.4.0'):
        tag='starpass-router-v'+v
        return {'tag_name':tag,'assets':[{'name':p+'_'+n+'_all.ipk','state':'uploaded','size':100,'digest':'sha256:'+'a'*64,'browser_download_url':'https://github.com/'+updater.REPO+'/releases/download/'+tag+'/'+p+'_'+n+'_all.ipk'} for p,n in [('xianniu-router','0.5.1'),('luci-app-starpass',v)]]}
    def test_selects_matching_router_only_not_previews_or_desktop(self):
        a=self.release();b=self.release('9.0.0');b['prerelease']=True
        value=updater.choose([{'tag_name':'desktop-v99.0.0'},a,b], '0.3.9')
        self.assertEqual(value['target'],'0.4.0');self.assertIsNone(updater.choose([a],'0.4.0'))
    def test_missing_or_untrusted_digest_origin_or_pair_is_not_installable(self):
        for key,value in [('digest',''),('browser_download_url','https://evil.example/p.ipk'),('state','new'),('size',999999999)]:
            r=self.release();r['assets'][0][key]=value;self.assertIsNone(updater.choose([r],'0.3.9'))
        r=self.release();r['assets'].pop();self.assertIsNone(updater.choose([r],'0.3.9'))
    def test_package_identity_and_unsafe_paths_are_rejected(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        import importlib.util
        spec=importlib.util.spec_from_file_location('builder',ROOT/'scripts/build-router-ipk.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'root.ipk';builder.build(dest,'0.4.0');data=dest.read_bytes()
        files=updater.validate_package(data,'luci-app-starpass','0.4.0');self.assertIn('usr/libexec/portalproxy/gateway/updater.py',files)
        for package,version in [('other','0.4.0'),('luci-app-starpass','0.1.0')]:
            with self.assertRaises(ValueError):updater.validate_package(data,package,version)
        with self.assertRaises(ValueError):updater.contents(builder.tar_gz({'../escape':(b'x',0o600)}),10)
    def test_corrupt_download_does_not_pause_or_install(self):
        candidate=updater.choose([self.release()],'0.3.9');candidate['available']=True
        with tempfile.TemporaryDirectory() as d,patch('updater.ROOT',Path(d)),patch('updater.read',return_value={'available':True,'checked_at':updater.time.time()}),patch('updater.check',return_value=candidate),patch('updater.installed',return_value='0.3.9'),patch('updater.request',return_value=({},b'CORRUPT')),patch('updater.write'),patch('updater.subprocess.run') as run:
            with self.assertRaises(ValueError):updater.install()
            run.assert_not_called()
    def test_install_runs_verified_paired_packages_preserves_configs(self):
        candidate=updater.choose([self.release()],'0.3.9');candidate['available']=True
        for asset in candidate['packages'].values():asset['size']=2;asset['sha256']=hashlib.sha256(b'OK').hexdigest()
        versions={'xianniu-router':'0.5.1','luci-app-starpass':'0.3.9'};events=[]
        def run(args,**kw):
            events.append(args)
            if args[:2]==['opkg','install']:versions['luci-app-starpass']='0.4.0'
            return Mock(returncode=0)
        with tempfile.TemporaryDirectory() as d,patch('updater.ROOT',Path(d)),patch('updater.read',return_value={'available':True,'checked_at':updater.time.time()}),patch('updater.check',return_value=candidate),patch('updater.installed',side_effect=lambda p:versions[p]),patch('updater.request',return_value=({},b'OK')),patch('updater.validate_package'),patch('updater.write') as write,patch('updater.backup',return_value='/private/backup'),patch('updater.shutil.disk_usage',return_value=Mock(free=100000000)),patch('control.pause_accelerator') as pause,patch('updater.subprocess.run',side_effect=run):
            updater.install();pause.assert_called_once();self.assertEqual(write.call_args.kwargs['phase'],'done')
            self.assertEqual(events[0][:3],['opkg','--noaction','install']);self.assertEqual(events[1][:2],['opkg','install'])
            self.assertEqual(len(events[1]),4)

if __name__=='__main__':unittest.main()
