#!/usr/bin/env python3
"""Exercise real Mihomo filters/selectors in an explicitly isolated test system.

Starts an isolated loopback core; do not run alongside a user's OpenClash. All
fixture nodes and health/DNS endpoints are loopback-only, with no subscription
download or Internet request. This is not a real-provider or game test.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

RENDER = r'''
package.path='src/?.lua;'..package.path
local config=require 'config'
local fs=require 'nixio.fs'
local json=require 'luci.jsonc'
local root,mode,name,proxy,api,dns=unpack(arg)
local core=config.render({listen_ip='192.168.50.2',client_ip='192.168.50.30',local_dns='127.0.0.1',
 bootstrap_dns='127.0.0.1',subscription_url='https://subscription.example.com/fixture',
 selection_mode=mode,preferred_node=name,backend_port=proxy,api_port=api,dns_port=dns,
 health_url='https://127.0.0.1:1/',doh_url='https://127.0.0.1:1/dns-query'},string.rep('a',64))
assert(fs.mkdir(root..'/providers','700'))
assert(fs.writefile(root..'/config.yaml',config.to_yaml(core,json.stringify)))
'''


def ports():
    sockets=[]
    try:
        for _ in range(3):
            s=socket.socket();s.bind(('127.0.0.1',0));sockets.append(s)
        return [s.getsockname()[1] for s in sockets]
    finally:
        for s in sockets:s.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('core',type=Path)
    parser.add_argument('--isolated',action='store_true',required=True)
    args=parser.parse_args()
    core=args.core.resolve()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    cases=[('auto','',['HK fixture','JP fixture','日本 [A]+ 🚀','US fixture','REJECT']),
           ('preferred','JP fixture',['JP fixture','HK fixture','日本 [A]+ 🚀','US fixture','REJECT']),
           ('fixed','JP fixture',['JP fixture','REJECT']),
           ('fixed','日本 [A]+ 🚀',['日本 [A]+ 🚀','REJECT']),
           ('fixed','missing',['REJECT'])]
    for mode,name,expected in cases:
        with tempfile.TemporaryDirectory(prefix='starpass-real-core-') as tmp:
            root=Path(tmp);proxy,api,dns=ports()
            subprocess.run(['lua','-',tmp,mode,name,str(proxy),str(api),str(dns)],input=RENDER,text=True,check=True)
            nodes=[{'name':n,'type':'socks5','server':'127.0.0.1','port':9} for n in ['US fixture','JP fixture','HK fixture','日本 [A]+ 🚀']]
            nodes.append({'name':'JP direct decoy','type':'direct'})
            (root/'providers/subscription.yaml').write_text(json.dumps({'proxies':nodes},ensure_ascii=False),encoding='utf-8')
            with (root/'core.log').open('w') as log:
                process=subprocess.Popen([str(core),'-d',tmp,'-f',str(root/'config.yaml')],stdout=log,stderr=log)
                try:
                    request=urllib.request.Request(f'http://127.0.0.1:{api}/proxies/PORTAL',headers={'Authorization':'Bearer '+'a'*64})
                    actual=None
                    for _ in range(100):
                        if process.poll() is not None:raise AssertionError('Core exited: '+(root/'core.log').read_text()[-2000:])
                        try:
                            with opener.open(request,timeout=.5) as response:actual=json.load(response)
                            initialized=urllib.request.Request(f'http://127.0.0.1:{api}/proxies',headers={'Authorization':'Bearer '+'a'*64})
                            with opener.open(initialized,timeout=.5) as response:state=json.load(response)
                            if 'HK fixture' in state.get('proxies',{}) and actual['all']==expected:break
                            time.sleep(.1)
                        except OSError:time.sleep(.1)
                    assert actual is not None,'Core API did not become ready'
                    assert actual['all']==expected,(mode,name,actual['all'],expected,(root/'core.log').read_text()[-2000:])
                    if mode=='fixed':assert actual['now']==expected[0],actual
                    print(f'PASS real core {mode} {name or "regional order"}: exact candidates, direct excluded, REJECT retained',flush=True)
                finally:
                    process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':main()
