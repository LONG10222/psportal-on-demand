"""CurrentUser DPAPI storage. No plaintext credential fallback."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise OSError('Windows DPAPI is required')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(result.data)


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(os.environ['LOCALAPPDATA']) / 'StarPassXianniuPreview'
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'session.dpapi'
        self.lock_file = None

    def lock(self):
        import msvcrt
        self.lock_file = open(self.root / 'instance.lock', 'a+b')
        self.lock_file.seek(0)
        if not self.lock_file.read(1):
            self.lock_file.write(b'0'); self.lock_file.flush()
        self.lock_file.seek(0)
        try:
            msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock_file.close()
            raise RuntimeError('鲜牛预览已经运行，请使用现有窗口') from None

    def load(self):
        if self.path.exists():
            return json.loads(crypt(self.path.read_bytes(), True))
        return dict(account={}, auth={'plain_second': True, 'x': ''}, node={},
                    hardware='StarPass-Windows-' + secrets.token_hex(16),
                    client_os_info='StarPass Windows Preview', client_os_version='Windows',
                    game_id=797, profile={'area_id': 933, 'line_id': 122, 'isp_type': 3},
                    session_mode='managed', dns_server='192.168.31.1', devices=[],
                    http_port=18082, socks_port=18092, listen_host='127.0.0.1', steam_store_direct=True)

    def save(self, config):
        # Internal ownership is process-local, never import it from a file.
        clean = {k: v for k, v in config.items() if not k.startswith('_')}
        data = crypt(json.dumps(clean, ensure_ascii=False).encode('utf-8'))
        temporary = self.root / ('session.' + secrets.token_hex(8) + '.tmp')
        try:
            temporary.write_bytes(data)
            os.replace(temporary, self.path)
            # A separate credential-free projection is used by the optional,
            # user-run administrator firewall helper. Never decrypt in it.
            (self.root / 'lan-access.json').write_text(json.dumps({k:clean.get(k) for k in
                ('listen_host','http_port','socks_port','devices')}),encoding='utf-8')
        finally:
            temporary.unlink(missing_ok=True)

    def journal(self, state):
        path = self.root / 'ownership.json'
        if state is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(json.dumps({'state': state}), encoding='utf-8')

    def unresolved(self):
        return (self.root / 'ownership.json').exists()
