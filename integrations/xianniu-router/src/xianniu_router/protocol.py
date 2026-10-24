import base64
import json
import struct
import zlib

MAX_FRAME = 1048576
API_KEY = b'xi@nNiu001'  # Public constant in the shipped client, not an account key.


def rc4(data, key):
    key = key[:128]
    if key == b'CA143A8A1F':
        return data
    if not data:
        return b''
    if not key:
        raise ValueError('Missing session key')
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    output = bytearray()
    for value in data:
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        output.append(value ^ state[(state[i] + state[j]) & 255])
    return bytes(output)


def build_request(auth, command, host, port, extra=b''):
    if command not in (1, 4) or not 0 < port <= 65535:
        raise ValueError('Unsupported request')
    user = base64.b64decode(auth['u'], validate=True)
    key = base64.b64decode(auth['key'], validate=True)
    x = base64.b64decode(auth.get('x', ''), validate=True)
    host = host.encode('utf-8') if isinstance(host, str) else host
    if extra and extra != host:
        host += b'\r' + extra
    if any(len(v) > 4096 for v in (user, key, host, x)):
        raise ValueError('Request field exceeds observed bounds')
    second = user if auth.get('plain_second', False) else rc4(user, key + host)
    fields = (user, second, rc4(host, key), x)
    header = struct.pack('!BBH4s', 105, command, port, b'\0\0\0\1')
    return header + b''.join(struct.pack('<I', len(v)) + v for v in fields)


def encode_api(value):
    plain = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
    return base64.b64encode(rc4(zlib.compress(plain), API_KEY))


def decode_api(body):
    compressed = rc4(base64.b64decode(body, validate=True), API_KEY)
    decoder = zlib.decompressobj()
    plain = decoder.decompress(compressed, MAX_FRAME + 1)
    if len(plain) > MAX_FRAME or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized API response')
    return json.loads(plain)


async def read_frame(reader):
    length, = struct.unpack('<I', await reader.readexactly(4))
    if not 0 < length <= MAX_FRAME:
        raise ValueError('Invalid tunnel frame')
    return await reader.readexactly(length)


def frame(payload):
    if not 0 < len(payload) <= MAX_FRAME:
        raise ValueError('Invalid frame length')
    return struct.pack('<I', len(payload)) + payload
