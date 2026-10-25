"""Read-only LAN discovery. No DHCP, gateway or interface configuration writes."""
import ipaddress
import json
import re
from pathlib import Path
import subprocess


def mac_key(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}',value):return ''
    value=value.lower()
    return value if value not in ('00:00:00:00:00:00','ff:ff:ff:ff:ff:ff') and not int(value[:2],16)&1 else ''


def device_preferences(value):
    result={}
    for key,row in value.get('devices',{}).items():
        if not isinstance(row,dict):continue
        identity=mac_key(key) or mac_key(row.get('mac'))
        if not identity:continue
        last=row.get('last_ip',key if not mac_key(key) else '')
        result[identity]={**row,'mac':identity,'last_ip':last}
    return {**value,'version':2,'devices':result}


def read_command(args):
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=4)
        return result.stdout.strip() if result.returncode==0 else ''
    except (OSError,subprocess.TimeoutExpired):return ''


def option(name,default=''):
    return read_command(['uci','-q','get','xianniu-router.main.'+name]) or default


def discover(config,preferences):
    interface=option('interface',config.get('interface','br-lan'))
    rows={};local=[];networks=[]
    try:
        gateways={r.get('gateway') for r in json.loads(read_command(['ip','-j','-4','route','show','default']) or '[]')}
    except ValueError:gateways=set()
    try:addresses=json.loads(read_command(['ip','-j','-4','address','show','dev',interface]) or '[]')
    except ValueError:addresses=[]
    for link in addresses:
        for item in link.get('addr_info',[]):
            try:
                address=ipaddress.IPv4Interface(str(item['local'])+'/'+str(item['prefixlen']))
                local.append(str(address.ip));networks.append(address.network)
            except (KeyError,ValueError):pass

    def add(address,name='',mac='',online=False,source='saved'):
        try:ip=ipaddress.IPv4Address(address)
        except (ValueError,TypeError):return
        if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:return
        if str(ip) in local or str(ip) in gateways:return
        if networks and not any(ip in network and ip not in (network.network_address,network.broadcast_address) for network in networks):return
        row=rows.setdefault(str(ip),{'ip':str(ip),'name':'设备 '+str(ip),'mac':'','seen':False,'source':source})
        if name and name!='*':row['name']=str(name)[:64]
        if mac_key(mac):row['mac']=mac_key(mac)
        row['seen']=row['seen'] or online
        if source!='saved':row['source']=source

    saved=device_preferences(preferences).get('devices',{})
    for identity,preset in saved.items():add(preset.get('last_ip',''),preset.get('name',''),identity)
    for address in config.get('devices',[]):add(address)
    for address in option('devices').split():add(address)
    try:
        for line in Path('/tmp/dhcp.leases').read_text().splitlines():
            fields=line.split()
            if len(fields)>=4:add(fields[2],fields[3],fields[1],source='dhcp')
    except OSError:pass
    try:neighbors=json.loads(read_command(['ip','-j','-4','neigh','show','dev',interface]) or '[]')
    except ValueError:neighbors=[]
    for item in neighbors:
        if not item.get('lladdr'):continue
        state=item.get('state',[])
        if isinstance(state,str):state=[state]
        add(item.get('dst'),mac=item.get('lladdr',''),online=any(s in ('REACHABLE','DELAY','PROBE','PERMANENT') for s in state),source='neighbor')
    # Prefer live observations over the stored last IP for the same MAC.
    identities={}
    for row in rows.values():
        identity=mac_key(row['mac'])
        rank=(row['seen'],row['source']!='saved')
        if identity and (identity not in identities or rank>identities[identity][0]):identities[identity]=(rank,row['ip'])
    rows={ip:row for ip,row in rows.items() if not row['mac'] or identities[row['mac']][1]==ip}
    for row in rows.values():
        preset=saved.get(mac_key(row['mac']))
        row['note']=str(preset.get('note',''))[:64] if preset else ''
        if row['note']:row['name']=row['note']
        if preset:
            profile={key:preset[key] for key in ('game_id','area_id','line_id') if key in preset}
            if profile:row['preset']=profile
    host=option('http_host','127.0.0.1')
    if host=='127.0.0.1' and local:host=local[0]
    return {'devices':sorted(rows.values(),key=lambda r:(not bool(r.get('preset')),not r['seen'],r['ip'])),
            'host':host,'port':int(option('http_port','10082')),'interface':interface,
            'local':local}
