"""Own and roll back only this service's nftables rules and policy route."""
import ipaddress
import json
import os
import re
import subprocess
import fcntl
import functools
import threading
from contextlib import contextmanager
from pathlib import Path

OWNER = 'xianniu-router/0.1'
TABLE = 'xianniu_router'
MARK = '0x584e0002'
ROUTE_TABLE = '32024'
PRIORITY = '32024'
STATE = Path('/var/run/xianniu-router-routing.json')
TAGS = ('xianniu-router-relay', 'xianniu-router-dns')
_mutex = threading.RLock()
_depth = 0


@contextmanager
def routing_lock():
    global _depth
    with _mutex:
        if _depth:
            _depth += 1
            try:
                yield
            finally:
                _depth -= 1
        else:
            with open('/var/run/xianniu-router.lock', 'a') as lock:
                os.chmod(lock.name, 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX)
                _depth = 1
                try:
                    yield
                finally:
                    _depth = 0
                    fcntl.flock(lock, fcntl.LOCK_UN)


def locked(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        with routing_lock():
            return function(*args, **kwargs)
    return wrapped


def command(*args, check=True, input=None):
    result = subprocess.run(args, text=True, input=input, capture_output=True)
    if check and result.returncode:
        raise RuntimeError('Routing command failed: ' + args[0] + ': ' + result.stderr[:1000])
    return result


def save(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE)


def chain_rules(chain):
    result = command('nft', '-j', 'list', 'chain', 'inet', 'fw4', chain, check=False)
    if result.returncode:
        return None
    return [entry['rule'] for entry in json.loads(result.stdout)['nftables'] if 'rule' in entry]


@locked
def exclusions(config):
    """Restore narrowly scoped bypasses if another firewall service reloads."""
    state = json.loads(STATE.read_text())
    if state.get('owner') != OWNER:
        raise RuntimeError('Routing ownership mismatch')
    devices = [str(ipaddress.IPv4Address(v)) for v in config['devices']]
    interface = config.get('interface', 'br-lan')
    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,15}', interface):
        raise ValueError('Invalid interface')
    for chain in ('dstnat', 'openclash_mangle'):
        rules = chain_rules(chain)
        if rules is None:
            if chain == 'dstnat':
                raise RuntimeError('fw4 dstnat is unavailable')
            continue
        if not any(rule.get('comment') == TAGS[0] for rule in rules):
            command('nft', 'insert', 'rule', 'inet', 'fw4', chain,
                    'meta', 'mark', MARK, 'return', 'comment', '"' + TAGS[0] + '"')
        if not any(rule.get('comment') == TAGS[1] for rule in rules):
            text = ('insert rule inet fw4 ' + chain + ' iifname "' + interface + '" ip saddr { ' +
                    ', '.join(devices) + ' } udp dport 53 return comment "' + TAGS[1] + '"\n')
            command('nft', '-f', '-', input=text)


@locked
def install(config, transparent_port, dns_port):
    if STATE.exists():
        remove()
    if not config.get('devices'):
        raise ValueError('Choose at least one device before enabling routing')
    devices = [str(ipaddress.IPv4Address(v)) for v in config['devices']]
    interface = config.get('interface', 'br-lan')
    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,15}', interface):
        raise ValueError('Invalid interface')
    if not all(0 < int(p) <= 65535 for p in (transparent_port, dns_port)):
        raise ValueError('Both transparent and DNS listeners must be enabled')
    existing = command('nft', 'list', 'table', 'inet', TABLE, check=False)
    routes = command('ip', 'route', 'show', 'table', ROUTE_TABLE, check=False)
    rules = command('ip', 'rule', 'show').stdout
    if existing.returncode == 0 or routes.stdout.strip() or re.search(r'^' + PRIORITY + r':', rules, re.M) or MARK in rules:
        raise RuntimeError('Reserved routing identifiers are already in use')
    state = dict(owner=OWNER, route=False, rule=False, table=False)
    save(state)
    prefix = 'iifname "' + interface + '" ip saddr @clients_v4 '
    text = ('table inet ' + TABLE + ' {\n comment "' + OWNER + '"\n'
            ' set clients_v4 { type ipv4_addr; elements = { ' + ', '.join(devices) + ' }; }\n'
            ' chain relay {\n type filter hook prerouting priority -151; policy accept;\n ' +
            prefix + 'udp dport 53 return\n ' + prefix +
            'ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, '
            '172.16.0.0/12, 192.168.0.0/16, 198.18.0.0/15, 224.0.0.0/4, 240.0.0.0/4 } return\n ' +
            prefix + 'meta l4proto { tcp, udp } counter meta mark set ' + MARK +
            ' tproxy ip to 127.0.0.1:' + str(transparent_port) + ' accept\n }\n'
            ' chain dns {\n type nat hook prerouting priority -101; policy accept;\n ' +
            prefix + 'udp dport 53 counter redirect to :' + str(dns_port) + '\n }\n}\n')
    try:
        command('nft', '-c', '-f', '-', input=text)
        command('ip', 'route', 'add', 'local', '0.0.0.0/0', 'dev', 'lo', 'table', ROUTE_TABLE)
        state['route'] = True
        save(state)
        command('ip', 'rule', 'add', 'priority', PRIORITY, 'fwmark', MARK + '/0xffffffff', 'table', ROUTE_TABLE)
        state['rule'] = True
        save(state)
        exclusions(config)
        command('nft', '-f', '-', input=text)
        state['table'] = True
        save(state)
    except BaseException:
        remove()
        raise


@locked
def remove():
    if not STATE.exists():
        return
    state = json.loads(STATE.read_text())
    if state.get('owner') != OWNER:
        raise RuntimeError('Refusing to remove routing owned by another service')
    result = command('nft', '-j', 'list', 'table', 'inet', TABLE, check=False)
    if result.returncode == 0:
        tables = [v['table'] for v in json.loads(result.stdout)['nftables'] if 'table' in v]
        if not tables or tables[0].get('comment') != OWNER:
            raise RuntimeError('Refusing to remove a table with a different owner')
        command('nft', 'delete', 'table', 'inet', TABLE)
    for chain in ('dstnat', 'openclash_mangle'):
        for rule in chain_rules(chain) or []:
            if rule.get('comment') in TAGS:
                command('nft', 'delete', 'rule', 'inet', 'fw4', chain, 'handle', str(int(rule['handle'])))
    if state.get('rule'):
        command('ip', 'rule', 'del', 'priority', PRIORITY, 'fwmark', MARK + '/0xffffffff', 'table', ROUTE_TABLE, check=False)
    if state.get('route'):
        command('ip', 'route', 'del', 'local', '0.0.0.0/0', 'dev', 'lo', 'table', ROUTE_TABLE, check=False)
    STATE.unlink()


@locked
def ensure(config, transparent_port, dns_port):
    result = command('nft', 'list', 'table', 'inet', TABLE, check=False)
    if result.returncode:
        install(config, transparent_port, dns_port)
    else:
        exclusions(config)
