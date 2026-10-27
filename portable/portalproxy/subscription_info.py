"""Display only server-provided subscription accounting, never estimated quota."""
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
import time
import math
from .i18n import text


def from_headers(headers, url='') -> dict:
    result = {'source': urlsplit(url).hostname or '', 'updated_at': int(time.time())}
    value = headers.get('subscription-userinfo', '')
    if not isinstance(value, str) or len(value) > 4096:
        return result
    for item in value.split(';'):
        key, separator, number = item.strip().partition('=')
        number = number.strip()
        if separator and key in ('upload', 'download', 'total', 'expire') and number.isascii() and number.isdigit() and len(number) <= 19:
            value = int(number)
            if value <= (253402300799 if key == 'expire' else 2**63-1):
                result[key] = value
    return result


def display(info: dict | None, language: str, *, compact=False) -> str:
    tr = lambda key, **values: text(key, language, **values)
    if not isinstance(info, dict) or not info:
        return tr('Subscription details appear after import.')
    def size(value):
        if value is None: return tr('Not provided')
        for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB'):
            if value < 1024 or unit == 'EiB': return f'{value:.2f} {unit}'
            value /= 1024
    used = info['upload'] + info['download'] if all(type(info.get(k)) is int and 0 <= info[k] <= 2**63-1 for k in ('upload', 'download')) else None
    total = info.get('total') if type(info.get('total')) is int and 0 < info['total'] <= 2**63-1 else None
    remaining = max(0, total-used) if total is not None and used is not None else None
    def date(value, updated=False):
        try:
            pattern=('%H:%M:%S' if updated else '%Y-%m-%d') if compact else '%Y-%m-%d %H:%M UTC+08:00'
            return datetime.fromtimestamp(value, timezone(timedelta(hours=8))).strftime(pattern)
        except (ValueError, OverflowError, OSError):
            return tr('Not provided')
    expiration = tr('Not provided')
    if type(info.get('expire')) is int and 0 < info['expire'] <= 253402300799:
        expiration = date(info['expire'])
        if info['expire'] < time.time(): expiration += ' · ' + tr('Expired')
        else: expiration += ' · ' + tr('{days} days remaining', days=math.ceil((info['expire']-time.time())/86400))
    result = tr('Used: {used} / Total: {total}\nRemaining: {remaining}\nExpires: {expiration}',
              used=size(used), total=size(total), remaining=size(remaining), expiration=expiration)
    if used is not None and not compact:
        result += '\n' + tr('Uploaded: {upload} · Downloaded: {download}',
                             upload=size(info['upload']), download=size(info['download']))
    if info.get('source_kind') == 'clash-cache':
        result = tr('Clash local cache · read-only, not live') + '\n' + result
        if isinstance(info.get('provider_name'), str):
            result = tr('Subscription: {name}', name=info['provider_name'][:120]) + '\n' + result
    elif info.get('source_kind') == 'clash-live':
        result = tr('Clash 当前订阅 · 服务端用量') + '\n' + result
        if isinstance(info.get('provider_name'), str): result = info['provider_name'][:120] + '\n' + result
    elif isinstance(info.get('source'), str) and info['source']:
        result = tr('Provider: {source}', source=info['source'][:253]) + '\n' + result
    if type(info.get('updated_at')) is int and 0 < info['updated_at'] <= 253402300799:
        updated = date(info['updated_at'],updated=True)
        result += '\n' + tr('Last updated: {when}', when=updated)
    return result


def usage_percent(info):
    if not isinstance(info, dict): return None
    if not all(type(info.get(key)) is int and 0 <= info[key] <= 2**63-1 for key in ('upload', 'download', 'total')) or not info['total']:
        return None
    return min(100, 100*(info['upload']+info['download'])/info['total'])
