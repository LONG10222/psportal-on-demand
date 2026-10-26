"""Traffic through owned proxy inputs, split by validated destination scope."""
import math
import time


class TrafficMeter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.previous = clock()
        self.bytes = {scope: dict(upload=0, download=0) for scope in ('local', 'external')}
        self.baseline = {scope: dict(row) for scope, row in self.bytes.items()}
        self.rates = {scope: dict(upload=0.0, download=0.0) for scope in self.bytes}

    def add(self, scope, direction, count):
        if scope in self.bytes and direction in ('upload', 'download') and count > 0:
            self.bytes[scope][direction] += count

    def snapshot(self):
        now = self.clock()
        elapsed = now - self.previous
        if elapsed >= 1:
            for scope, row in self.bytes.items():
                for direction, count in row.items():
                    self.rates[scope][direction] = (count - self.baseline[scope][direction]) / elapsed
            self.baseline = {scope: dict(row) for scope, row in self.bytes.items()}
            self.previous = now
        return {scope: {direction + '_bytes': count for direction, count in row.items()} |
                {direction + '_bps': speed for direction, speed in self.rates[scope].items()}
                for scope, row in self.bytes.items()}


def validate_traffic(value):
    if not isinstance(value, dict) or set(value) != {'local', 'external'}:
        raise ValueError('Invalid traffic scopes')
    result = {}
    for scope, row in value.items():
        if not isinstance(row, dict): raise ValueError('Invalid traffic record')
        clean = {}
        for direction in ('upload', 'download'):
            count, speed = row.get(direction + '_bytes'), row.get(direction + '_bps')
            if type(count) is not int or not 0 <= count <= 2**63-1:
                raise ValueError('Invalid traffic counter')
            if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 10**15:
                raise ValueError('Invalid traffic rate')
            clean.update({direction + '_bytes': count, direction + '_bps': speed})
        result[scope] = clean
    return result


class MeteredReader:
    def __init__(self, raw, record): self.raw, self.record = raw, record
    def __getattr__(self, key): return getattr(self.raw, key)
    async def read(self, *args):
        data = await self.raw.read(*args); self.record(len(data)); return data
    async def readuntil(self, *args):
        data = await self.raw.readuntil(*args); self.record(len(data)); return data
    async def readexactly(self, *args):
        data = await self.raw.readexactly(*args); self.record(len(data)); return data


class MeteredWriter:
    def __init__(self, raw, record): self.raw, self.record = raw, record
    def __getattr__(self, key): return getattr(self.raw, key)
    def write(self, data):
        self.raw.write(data); self.record(len(data))


def byte_text(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB'):
        if value < 1024 or unit == 'EiB': return f'{value:.1f} {unit}'
        value /= 1024


def display(value):
    try: rows = validate_traffic(value)
    except ValueError: return '启动后显示实时流量'
    return '\n'.join(label + '  ↑ ' + byte_text(rows[scope]['upload_bps']) + '/s  ↓ ' +
        byte_text(rows[scope]['download_bps']) + '/s\n本次累计 ↑ ' + byte_text(rows[scope]['upload_bytes']) +
        '  ↓ ' + byte_text(rows[scope]['download_bytes']) for scope, label in (('local', '局域网'), ('external', '外网')))
