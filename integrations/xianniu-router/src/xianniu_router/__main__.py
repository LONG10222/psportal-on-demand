import argparse
import asyncio
import ipaddress
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from .runtime import Service
from .control import APIError


def main():
    parser = argparse.ArgumentParser(description='Experimental Xianniu IPv4 native relay')
    parser.add_argument('--config', required=True)
    parser.add_argument('--socks-port', type=int, default=10889)
    parser.add_argument('--transparent-port', type=int, default=0)
    parser.add_argument('--dns-port', type=int, default=0)
    parser.add_argument('--http-host', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, default=0)
    parser.add_argument('--status-file')
    parser.add_argument('--bypass-gid', type=int)
    parser.add_argument('--manage-routing', action='store_true')
    parser.add_argument('--remove-routing', action='store_true')
    parser.add_argument('--uci', action='store_true')
    args = parser.parse_args()
    if args.remove_routing:
        from .routing import remove
        remove()
        return
    path = Path(args.config)
    if os.name == 'posix' and stat.S_IMODE(path.stat().st_mode) & 0o077:
        parser.error('Private config must have mode 0600')
    config = json.loads(path.read_text())
    config['_config_path']=str(path)
    config.pop('_owned_session_started', None)
    if args.uci:
        def option(name, default):
            result = subprocess.run(['uci', '-q', 'get', 'xianniu-router.main.' + name],
                                    text=True, capture_output=True)
            return result.stdout.strip() if result.returncode == 0 else default
        config['devices'] = option('devices', '').split()
        config['interface'] = option('interface', 'br-lan')
        config['steam_store_direct']=option('steam_store_direct','1')=='1'
        if option('http_enabled', '0') == '1':
            args.http_host = option('http_host', '127.0.0.1')
            args.http_port = int(option('http_port', '10082'))
    if not config.get('start_on_launch'):
        address = ipaddress.IPv4Address(config['node']['host'])
        if not address.is_global:
            parser.error('Node must be a public IPv4 address')
    for device in config.get('devices', []):
        ipaddress.IPv4Address(device)
    ipaddress.IPv4Address(args.http_host)
    for port in (args.socks_port, args.transparent_port, args.dns_port, args.http_port):
        if not 0 <= port <= 65535:
            parser.error('Invalid listen port')
    enabled_ports = [p for p in (args.socks_port, args.transparent_port, args.dns_port, args.http_port) if p]
    if len(enabled_ports) != len(set(enabled_ports)):
        parser.error('Listen ports must be distinct')
    if args.bypass_gid is not None:
        os.setegid(args.bypass_gid)
    try:
        asyncio.run(Service(config, args.status_file).run(
            args.socks_port, args.transparent_port, args.dns_port, args.manage_routing,
            args.http_host, args.http_port))
    except APIError as error:
        if args.status_file:
            Path(args.status_file).write_text(json.dumps({'running':False,'version':'0.4.4',
                'start_error_code':error.code,'message':error.user_message,
                'login_required':error.code in (400009,400010,400011,400024,400065)}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
