"""Product use cases, separate from Clash rule/global/direct routing modes.

This module only derives our owned HTTP listener configuration. It never changes
OS proxy, VPN, DNS or firewall settings, nor the subscription's routing rules.
The UI keeps editable LAN preferences separate from the effective listener so a
loopback-only session cannot erase a previously configured device allowlist.
"""
from __future__ import annotations

import ipaddress

MODES = ('game', 'mixed', 'clash', 'accelerator')
LABELS = {'game': 'Game mode', 'mixed': 'Mixed mode', 'clash': 'Clash mode',
          'accelerator': 'Accelerator mode'}
NOTES = {
    'game': 'Game devices only: LAN HTTP/CONNECT proxy; the listener host IP is excluded. UDP game acceleration is not provided.',
    'mixed': 'Game devices + local apps: LAN HTTP/CONNECT proxy, including this computer. Configure each app manually.',
    'clash': 'Local apps only: HTTP/CONNECT on 127.0.0.1, with no LAN access. Full profiles require external Mihomo; embedded support is limited.',
    'accelerator': 'Separate accelerator sharing: explicitly choose the Windows Steam web relay or a verified local HTTP/SOCKS5 proxy. LAN devices only; acceleration, voice and game UDP are not verified.',
}
_PRIVATE = tuple(ipaddress.IPv4Network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def is_lan(value):
    try:
        ip = ipaddress.IPv4Address(value)
        return any(ip in net for net in _PRIVATE)
    except (ValueError, TypeError):
        return False


def infer_mode(values):
    """Migrate old listeners without widening their existing access policy."""
    if 'product_mode' in values:
        if values['product_mode'] not in MODES:
            raise ValueError('Choose Game, Mixed, Clash or Accelerator mode.')
        return values['product_mode']
    host, clients = values.get('listen_host'), values.get('allowed_clients', [])
    if host == '127.0.0.1' and clients == ['127.0.0.1']:
        return 'clash'
    return 'mixed' if host and isinstance(clients, list) and host in clients else 'game'


def editable_config(values):
    """Restore LAN form fields from our own non-effective preferences."""
    result = dict(values, product_mode=infer_mode(values))
    saved = values.get('product_lan_preferences')
    if (isinstance(saved, dict) and isinstance(saved.get('listen_host'), str)
            and isinstance(saved.get('allowed_clients'), list)
            and all(isinstance(item, str) for item in saved['allowed_clients'])):
        result.update(listen_host=saved['listen_host'], allowed_clients=list(saved['allowed_clients']))
    elif result['product_mode'] == 'clash':
        # An old local-only config had no LAN preferences to restore.
        result.update(listen_host='', allowed_clients=[])
    return result


def listener_policy(mode, host, clients):
    """Return the actual bind address and exact accepted source addresses."""
    if mode not in MODES:
        raise ValueError('Choose Game, Mixed, Clash or Accelerator mode.')
    if mode == 'clash':
        return '127.0.0.1', ['127.0.0.1']
    if not is_lan(host):
        raise ValueError('Game, Mixed and Accelerator modes need a private LAN IPv4 address. Use Start sharing or Advanced settings.')
    if not isinstance(clients, list) or not all(is_lan(client) for client in clients):
        raise ValueError('Allowed devices must be specific private LAN IPv4 addresses.')
    allowed = list(dict.fromkeys(client for client in clients if client != host))
    if mode == 'mixed':
        allowed.append(host)
    if not allowed:
        raise ValueError(('Accelerator mode' if mode == 'accelerator' else 'Game mode') +
                         ' needs at least one allowed device other than this computer.')
    if len(allowed) > 256:
        raise ValueError('Choose at most 256 allowed device addresses.')
    return host, allowed


def effective_config(values):
    """Derive a launch/save copy; never mutate form fields or source policies."""
    mode = infer_mode(values)
    host, clients = values.get('listen_host', ''), values.get('allowed_clients', [])
    effective_host, effective_clients = listener_policy(mode, host, clients)
    result = dict(values, product_mode=mode,
                  product_lan_preferences=dict(listen_host=host, allowed_clients=list(clients)),
                  listen_host=effective_host, allowed_clients=effective_clients)
    return result


def validate_effective(values):
    """Reject mode/ACL mismatches even when a config bypasses the desktop UI."""
    if 'product_mode' not in values:
        return  # Legacy CLI/config behavior stays unchanged.
    mode = infer_mode(values)
    host, clients = values.get('listen_host'), values.get('allowed_clients')
    expected_host, expected_clients = listener_policy(mode, host, clients)
    if (host != expected_host or not isinstance(clients, list)
            or set(clients) != set(expected_clients)
            or mode == 'clash' and clients != ['127.0.0.1']):
        raise ValueError('Product mode does not match the listener address and allowed devices.')


def infer_automatic(values):
    """Only explicit provenance can authorize replacing a saved device list.

    A legacy list equal to a small subnet might still be intentional manual
    access. Never guess automatic authorization from its address pattern.
    """
    return values.get('product_lan_automatic') is True
