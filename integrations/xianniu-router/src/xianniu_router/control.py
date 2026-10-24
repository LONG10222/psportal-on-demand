import base64
import http.client
import socket
import ssl
import time
import ipaddress

from .dns import resolve_real
from .protocol import encode_api, decode_api

API_HOST = 'api1.xianniu.com'


class APIError(RuntimeError):
    def __init__(self, code, message=''):
        self.code = code if isinstance(code, int) else None
        self.user_message = ''.join(c for c in str(message)[:180] if ord(c)>=32)
        super().__init__('API refused request; code=' + str(self.code))


def call_api(config, path, value):
    if path not in ('/client/accelerate/token', '/client/accelerate/linelist',
                    '/client/accelerate/start', '/client/accelerate/stop',
                    '/client/auth/login_token', '/client/auth/login', '/client/auth/other',
                    '/client/member/details', '/client/member/suspend', '/client/member/recovery'):
        raise ValueError('Unsupported API path')
    address = resolve_real(API_HOST, config.get('dns_server', '192.168.31.1'))
    context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(API_HOST, timeout=12, context=context)
    try:
        raw = socket.create_connection((address, 443), timeout=12)
        try:
            connection.sock = context.wrap_socket(raw, server_hostname=API_HOST)
        except BaseException:
            raw.close()
            raise
        headers={'Content-Type': 'application/json', 'User-Agent': 'xianniu-router-experimental/0.3'}
        if value.get('datetime'):
            headers['X-Request-Datetime']=str(value['datetime'])
        connection.request('POST', path, body=encode_api(value), headers=headers)
        response = connection.getresponse()
        body = response.read(1048577)
        if response.status != 200 or len(body) > 1048576:
            raise RuntimeError('API HTTP request failed')
        result = decode_api(body)
        if not isinstance(result, dict) or str(result.get('code')) not in ('0', '200'):
            # Server messages can contain account details; do not log them.
            message=result.get('msg','') if isinstance(result,dict) else ''
            for key in ('access_token','token','password'):
                if isinstance(value.get(key),str) and value[key]:message=str(message).replace(value[key],'[hidden]')
            raise APIError(result.get('code') if isinstance(result, dict) else None,message)
        return result.get('data', {})
    finally:
        connection.close()


def refresh(config, counters):
    account = config['account']
    value = {'game_id': int(config['game_id']), 'access_token': account['access_token'],
             'last_access_tick': int(time.monotonic() * 1000) & 0xffffffff,
             'send_bytes': counters['sent'], 'recv_bytes': counters['received'],
             'cdn_send_bytes': 0, 'cdn_recv_bytes': 0, 'speed': 0, 'cdn_speed': 0}
    result = call_api(config, '/client/accelerate/token', value)
    user, key = result.get('line_user'), result.get('line_token')
    if not isinstance(user, str) or not user or not isinstance(key, str) or not key:
        raise ValueError('Incomplete session credentials')
    return {**config['auth'], 'u': base64.b64encode(user.encode()).decode(),
            'key': base64.b64encode(key.encode()).decode()}


def start_session(config):
    profile = config['profile']
    value = {'access_token': config['account']['access_token'], 'game_id': int(config['game_id']),
             'area_id': int(profile['area_id']), 'line_id': int(profile['line_id']),
             'client_type': 0, 'hardware': config['hardware'], 'isp_type': int(profile.get('isp_type', 3))}
    data = call_api(config, '/client/accelerate/start', value)
    config['_owned_session_started'] = True
    address = str(ipaddress.IPv4Address(data['speed_ip']))
    port = int(data['pc_port'])
    if not ipaddress.ip_address(address).is_global or not 0 < port <= 65535:
        raise ValueError('Invalid selected node')
    if not data.get('line_user') or not data.get('line_token'):
        raise ValueError('Missing session credentials')
    auth = {**config.get('auth', {}), 'u': base64.b64encode(data['line_user'].encode()).decode(),
            'key': base64.b64encode(data['line_token'].encode()).decode()}
    return {'host': address, 'port': port}, auth


def stop_session(config, counters):
    if not config.get('_owned_session_started'):
        return False
    value = {'access_token': config['account']['access_token'], 'game_id': int(config['game_id']),
             'max_delay': 0, 'min_delay': 0, 'avg_delay': 0, 'packet_loss_rate': 0,
             'tran_kbytes': (counters['sent'] + counters['received']) // 1024, 'tran_cdn_kbytes': 0}
    call_api(config, '/client/accelerate/stop', value)
    config['_owned_session_started'] = False
    return True
