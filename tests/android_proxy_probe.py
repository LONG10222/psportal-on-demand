#!/usr/bin/env python3
"""Optional real Android system-proxy probe; no UI, accounts or game claims.

Build with a local Android SDK/JDK. Run only on an explicitly selected test
emulator. It installs a unique temporary instrumentation package, checks the
platform ProxySelector and HttpURLConnection, then restores proxy keys exactly
and uninstalls its own package. It refuses an existing proxy or probe package.
The router listener is managed separately by the operator.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import subprocess
import time
import zipfile

PACKAGE = 'org.starpass.routervalidationprobe'
PROXY_KEYS = ('http_proxy', 'global_http_proxy_host', 'global_http_proxy_port',
              'global_http_proxy_exclusion_list', 'global_proxy_pac_url')
MANIFEST = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.starpass.routervalidationprobe">
<uses-permission android:name="android.permission.INTERNET" />
<application android:label="StarPass router network probe" android:debuggable="true" android:usesCleartextTraffic="true" />
<instrumentation android:name=".Probe" android:targetPackage="org.starpass.routervalidationprobe" />
</manifest>'''
JAVA = r'''package org.starpass.routervalidationprobe;
import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.InputStream;
import java.io.IOException;
import java.net.*;
import java.util.List;

public final class Probe extends Instrumentation {
 private Bundle args;
 public void onCreate(Bundle b) { super.onCreate(b); args=b; start(); }
 public void onStart() {
  Bundle result=new Bundle();
  try {
   String host=args.getString("host"); int port=Integer.parseInt(args.getString("port"));
   boolean outage="true".equals(args.getString("outage"));
   String[] urls={"http://example.com/", "https://connectivitycheck.gstatic.com/generate_204"};
   int[] expected={200,204}; StringBuilder report=new StringBuilder();
   for(int i=0;i<urls.length;i++) {
    URI uri=URI.create(urls[i]);
    List<Proxy> proxies=ProxySelector.getDefault().select(uri);
    if(proxies.isEmpty() || proxies.get(0).type()!=Proxy.Type.HTTP)
     throw new IllegalStateException("system_proxy_missing");
    InetSocketAddress address=(InetSocketAddress)proxies.get(0).address();
    if(!host.equals(address.getHostString()) || port!=address.getPort())
     throw new IllegalStateException("system_proxy_mismatch");
    HttpURLConnection connection=(HttpURLConnection)uri.toURL().openConnection();
    connection.setConnectTimeout(12000); connection.setReadTimeout(12000);
    connection.setInstanceFollowRedirects(false);
    try {
     int status=connection.getResponseCode();
     if(outage) {
      if(connection.usingProxy()) throw new IllegalStateException("request_unexpectedly_succeeded");
      report.append(i==0?"HTTP=direct_fallback ":"HTTPS=direct_fallback ");
      continue;
     }
     if(!connection.usingProxy()) throw new IllegalStateException("proxy_bypassed");
     if(status!=expected[i]) throw new IllegalStateException("unexpected_http_status_"+status);
     try(InputStream in=connection.getInputStream()) {
      byte[] buffer=new byte[4096]; int total=0,n;
      while(total<16384 && (n=in.read(buffer))!=-1) total+=n;
     }
     report.append(i==0?"HTTP=200 ":"HTTPS=204 ");
    } catch(IOException e) {
     if(!outage) throw e;
     report.append(i==0?"HTTP=blocked ":"HTTPS=blocked ");
    } finally { connection.disconnect(); }
   }
   result.putString("result", "PASS "+report+"system_proxy_config_verified=true");
   finish(Activity.RESULT_OK,result);
  } catch(Exception e) {
   // Only our fixed failure codes are safe to report; redact platform messages.
   String code=e.getMessage();
   if(code==null || !code.matches("system_proxy_missing|system_proxy_mismatch|proxy_bypassed|request_unexpectedly_succeeded|unexpected_http_status_[0-9]+")) code="platform_error";
   result.putString("result","FAIL "+e.getClass().getSimpleName()+" "+code);
   finish(Activity.RESULT_CANCELED,result);
  }
 }
}'''


def command(args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def build(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tools = args.sdk / 'build-tools' / args.build_tools
    android = args.sdk / 'platforms' / args.platform / 'android.jar'
    java = args.java_home / 'bin' / ('java.exe' if os.name == 'nt' else 'java')
    javac = java.with_name('javac.exe' if os.name == 'nt' else 'javac')
    keytool = java.with_name('keytool.exe' if os.name == 'nt' else 'keytool')
    aapt = tools / ('aapt2.exe' if os.name == 'nt' else 'aapt2')
    source = out / 'Probe.java'; source.write_text(JAVA, encoding='utf-8')
    manifest = out / 'AndroidManifest.xml'; manifest.write_text(MANIFEST, encoding='utf-8')
    classes = out / 'classes'; classes.mkdir(exist_ok=True)
    dex = out / 'dex'; dex.mkdir(exist_ok=True)
    command([javac, '-source', '8', '-target', '8', '-classpath', android, '-d', classes, source])
    command([java, '-cp', tools / 'lib/d8.jar', 'com.android.tools.r8.D8', '--lib', android,
             '--min-api', '23', '--output', dex, *classes.rglob('*.class')])
    unsigned = out / 'probe-unsigned.apk'
    command([aapt, 'link', '-I', android, '--manifest', manifest, '--min-sdk-version', '23',
             '--target-sdk-version', '28', '-o', unsigned])
    with zipfile.ZipFile(unsigned, 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.write(dex / 'classes.dex', 'classes.dex')
    key = out / 'probe-debug.p12'
    if not key.exists():
        command([keytool, '-genkeypair', '-keystore', key, '-storepass', 'android',
                 '-alias', 'probe', '-keypass', 'android', '-keyalg', 'RSA', '-keysize', '2048',
                 '-validity', '365', '-dname', 'CN=Local router probe'])
    apk = out / 'probe.apk'
    command([java, '-jar', tools / 'lib/apksigner.jar', 'sign', '--ks', key,
             '--ks-pass', 'pass:android', '--ks-key-alias', 'probe', '--out', apk, unsigned])
    command([java, '-jar', tools / 'lib/apksigner.jar', 'verify', apk])
    print('Built and verified local network probe APK.')


def run(args):
    ipaddress.IPv4Address(args.host)
    if not 1024 <= args.port <= 65535:
        raise ValueError('Invalid port')
    def adb(*values):
        return command([args.adb, '-s', args.serial, *values])
    previous = {key: adb('shell', 'settings', 'get', 'global', key) for key in PROXY_KEYS}
    if any(value not in ('null', '', '0', ':0') for value in previous.values()):
        raise RuntimeError('Existing emulator proxy found; refusing to replace it.')
    if adb('shell', 'pm', 'list', 'packages', PACKAGE):
        raise RuntimeError('Probe package already exists; refusing to overwrite it.')
    installed = False
    try:
        response = adb('install', '--no-streaming', str(args.output / 'probe.apk'))
        if 'Success' not in response:
            raise RuntimeError('Probe installation did not succeed')
        installed = True
        adb('shell', 'settings', 'put', 'global', 'http_proxy', f'{args.host}:{args.port}')
        time.sleep(1)
        result = adb('shell', 'am', 'instrument', '-w', '-r', '-e', 'host', args.host,
                     '-e', 'port', str(args.port), '-e', 'outage', str(args.outage).lower(),
                     PACKAGE + '/.Probe')
        print(result)
        if 'result=PASS ' not in result:
            raise RuntimeError('Android application proxy test failed')
    finally:
        adb('shell', 'settings', 'put', 'global', 'http_proxy', ':0')
        time.sleep(1)
        for key, value in previous.items():
            if value == 'null': adb('shell', 'settings', 'delete', 'global', key)
            else: adb('shell', 'settings', 'put', 'global', key, value)
        time.sleep(1)
        restored = {key: adb('shell', 'settings', 'get', 'global', key) for key in PROXY_KEYS}
        if installed:
            adb('uninstall', PACKAGE)
        if restored != previous:
            raise RuntimeError('Emulator proxy restoration did not match original state')
        print('All five proxy settings restored; temporary probe package removed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    builder = sub.add_parser('build')
    builder.add_argument('--sdk', type=Path, required=True)
    builder.add_argument('--java-home', type=Path, required=True)
    builder.add_argument('--build-tools', default='35.0.0')
    builder.add_argument('--platform', default='android-36')
    builder.add_argument('--output', type=Path, required=True)
    runner = sub.add_parser('run')
    runner.add_argument('--adb', type=Path, required=True)
    runner.add_argument('--serial', required=True)
    runner.add_argument('--host', required=True)
    runner.add_argument('--port', type=int, default=10081)
    runner.add_argument('--output', type=Path, required=True)
    runner.add_argument('--outage', action='store_true',
                        help='Measure stopped-proxy behavior, including direct fallback; not a kill-switch assertion')
    args = parser.parse_args()
    build(args) if args.action == 'build' else run(args)
