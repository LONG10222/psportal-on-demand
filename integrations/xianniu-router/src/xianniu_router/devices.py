"""Read-only LAN discovery. No DHCP, gateway or interface configuration writes."""
import ipaddress
import json
from pathlib import Path
import subprocess


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
        if mac:row['mac']=str(mac)[:17].upper()
        row['seen']=row['seen'] or online

    saved=preferences.get('devices',{})
    for address,preset in saved.items():add(address,preset.get('name',''),preset.get('mac',''))
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
    for row in rows.values():
        if row['ip'] in saved:
            preset=saved[row['ip']]
            if preset.get('name'):row['name']=str(preset['name'])[:64]
            row['preset']={key:preset[key] for key in ('game_id','area_id','line_id') if key in preset}
    host=option('http_host','127.0.0.1')
    if host=='127.0.0.1' and local:host=local[0]
    return {'devices':sorted(rows.values(),key=lambda r:(not bool(r.get('preset')),not r['seen'],r['ip'])),
            'host':host,'port':int(option('http_port','10082')),'interface':interface,
            'local':local}
