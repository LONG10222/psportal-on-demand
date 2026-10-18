"""Owned Mihomo lifecycle. Never attaches to or terminates an unrelated core."""
import asyncio
import json
import http.client
import ssl
import queue
import threading
from urllib.parse import urlsplit
import os
from pathlib import Path
import secrets
import shutil
import socket
import tempfile
import time
import urllib.error
import urllib.request
from .config import render
from .process_env import launch_external


class CoreError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CoreError('Subscription redirects are disabled; use the final HTTPS URL')


def download_subscription(url, destination):
    # Resolve once, reject every non-public address, then pin TLS to an approved
    # numeric address while authenticating the original HTTPS hostname.
    from .policy import destination as classify
    deadline = time.monotonic() + 15
    connection = None
    active_socket = [None]
    expired = threading.Event()
    def abort_transfer():
        expired.set()
        sock = active_socket[0]
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    watchdog = threading.Timer(15, abort_transfer)
    watchdog.daemon = True
    watchdog.start()
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port or 443
        answers = queue.Queue(maxsize=1)
        def lookup():
            try:
                answers.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except Exception as exc:
                answers.put(exc)
        threading.Thread(target=lookup, daemon=True).start()
        result = answers.get(timeout=5)
        if isinstance(result, Exception):
            raise result
        addresses = list(dict.fromkeys(row[4][0] for row in result))
        if not addresses or any(classify(ip) != 'external' for ip in addresses):
            raise CoreError('Subscription DNS must resolve exclusively to public addresses')
        class PinnedHTTPS(http.client.HTTPSConnection):
            def connect(self):
                last = None
                for ip in addresses:
                    try:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError()
                        raw = socket.create_connection((ip, port), timeout=min(5, remaining))
                        active_socket[0] = raw
                        try:
                            self.sock = self._context.wrap_socket(raw, server_hostname=host)
                            active_socket[0] = self.sock
                            if expired.is_set():
                                self.sock.close()
                                raise TimeoutError()
                            return
                        except BaseException:
                            raw.close()
                            raise
                    except OSError as exc:
                        last = exc
                raise last or OSError('No subscription address available')
        connection = PinnedHTTPS(host, port, timeout=5, context=ssl.create_default_context())
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        connection.request('GET', path, headers={'User-Agent':'clash.meta/1.19.32 PSPortal-OnDemand/0.1', 'Accept-Encoding':'identity'})
        response = connection.getresponse()
        if response.status != 200:
            raise CoreError('Subscription requires HTTP 200; redirects are disabled')
        lengths = response.headers.get_all('Content-Length', [])
        transfers = response.headers.get_all('Transfer-Encoding', [])
        if len(lengths) > 1 or len(transfers) > 1 or (lengths and transfers):
            raise CoreError('Ambiguous subscription response framing')
        if lengths and (not lengths[0].isdigit() or int(lengths[0]) > 10 * 1024 * 1024):
            raise CoreError('Invalid or oversized subscription length')
        if transfers and transfers[0].lower() != 'chunked':
            raise CoreError('Unsupported subscription transfer encoding')
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise CoreError('Compressed subscription responses are unsupported')
        chunks, size = [], 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            chunk = response.read1(min(65536, 10 * 1024 * 1024 + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 10 * 1024 * 1024:
                raise CoreError('Subscription exceeds 10 MiB')
        if response.length not in (None, 0):
            raise CoreError('Subscription response was truncated')
        data = b''.join(chunks)
        if expired.is_set() or time.monotonic() >= deadline:
            raise TimeoutError()
        if not data:
            raise CoreError('Subscription is empty')
        data.decode('utf-8-sig')
        atomic_private(destination, data)
        from .subscription_info import from_headers
        return from_headers(response.headers, url)
    except CoreError:
        raise
    except Exception:
        raise CoreError('Subscription download failed; check HTTPS URL and connectivity') from None
    finally:
        watchdog.cancel()
        if connection:
            connection.close()


def atomic_private(path, data):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.new-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class CoreManager:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.active = 0
        self.last_used = time.monotonic()
        self.state = 'stopped'
        self.lock = asyncio.Lock()
        self.closing = False
        self.secret = secrets.token_hex(32)
        root = Path(config['data_dir'])
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_path = root / 'owner.lock'
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise CoreError('Runtime is already owned; if a previous process crashed, verify it has stopped before removing owner.lock') from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self.runtime = Path(tempfile.mkdtemp(prefix='session-', dir=root))
        (self.runtime / 'providers').mkdir(mode=0o700)
        self.monitor = None

    def start_monitor(self):
        if self.monitor is None:
            self.monitor = asyncio.create_task(self._idle_loop())

    def _request(self, path, method='GET', payload=None):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(f"http://127.0.0.1:{self.config['api_port']}{path}",
            data=None if payload is None else json.dumps(payload).encode(), method=method,
            headers={'Authorization':'Bearer '+self.secret, 'Content-Type':'application/json'})
        with opener.open(request, timeout=2) as response:
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise CoreError('Controller response too large')
            return json.loads(data) if data else {}

    async def _select(self):
        if self.config.get('profile_file'):
            return  # Imported groups/rules retain their own selection semantics.
        proxies = await asyncio.to_thread(self._request, '/proxies')
        group = proxies.get('proxies', {}).get('PORTAL', {})
        names = group.get('all', [])
        preferred = self.config['preferred_node']
        mode = self.config['selection_mode']
        if mode == 'fixed' and preferred not in names:
            raise CoreError('Fixed node is missing from the subscription')
        if mode == 'fixed':
            await asyncio.to_thread(self._request, '/proxies/PORTAL', 'PUT', {'name':preferred})
            verified = await asyncio.to_thread(self._request, '/proxies/PORTAL')
            if verified.get('now') != preferred:
                raise CoreError('Fixed node selection could not be verified')

    async def acquire(self):
        async with self.lock:
            if self.closing:
                raise CoreError('Proxy is stopping')
            if self.process is None or self.process.returncode is not None:
                try:
                    await asyncio.wait_for(self._start(), self.config['wakeup_timeout'])
                except TimeoutError:
                    raise CoreError('Core startup timed out') from None
            self.active += 1
            return '127.0.0.1', self.config['backend_port']

    async def release(self):
        async with self.lock:
            self.active = max(0, self.active - 1)
            self.last_used = time.monotonic()

    async def _start(self):
        self.state = 'starting'
        print('Core: starting', flush=True)
        self.process = None
        try:
            for port in (self.config['backend_port'], self.config['api_port']):
                probe = socket.socket()
                if os.name != 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                elif hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                try:
                    probe.bind(('127.0.0.1', port))
                finally:
                    probe.close()
            if self.config.get('profile_file'):
                from .profiles import render_profile
                operation = asyncio.to_thread(render_profile, self.config, self.secret, self.runtime)
            elif self.config.get('subscription_file'):
                def copy_provider():
                    with open(self.config['subscription_file'], 'rb') as stream:
                        data = stream.read(10 * 1024 * 1024 + 1)
                    if not data or len(data) > 10 * 1024 * 1024:
                        raise CoreError('Local subscription is empty or oversized')
                    data.decode('utf-8-sig')
                    atomic_private(self.runtime / 'providers/subscription.yaml', data)
                operation = asyncio.to_thread(copy_provider)
            else:
                operation = asyncio.to_thread(download_subscription, self.config['subscription_url'], self.runtime / 'providers/subscription.yaml')
            download = asyncio.create_task(operation)
            try:
                generated = await asyncio.shield(download)
            except asyncio.CancelledError:
                # Wait for bounded import/provider I/O before cleanup/replacement.
                try:
                    await download
                except Exception:
                    pass
                raise
            rendered = generated if self.config.get('profile_file') else render(self.config, self.secret)
            atomic_private(self.runtime / 'config.json', json.dumps(rendered).encode())
            args = (self.config['core_path'], '-d', str(self.runtime), '-f', str(self.runtime / 'config.json'))
            check = await launch_external(*args, '-t')
            try:
                result = await asyncio.wait_for(check.wait(), timeout=self.config['wakeup_timeout'])
            finally:
                if check.returncode is None:
                    check.kill()
                    await check.wait()
            if result:
                raise CoreError('Mihomo rejected the generated configuration or subscription')
            self.process = await launch_external(*args)
            deadline = time.monotonic() + self.config['wakeup_timeout']
            while time.monotonic() < deadline:
                if self.process.returncode is not None:
                    raise CoreError('Mihomo exited during startup')
                try:
                    await asyncio.to_thread(self._request, '/version')
                    reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.config['backend_port']), timeout=1)
                    writer.close()
                    await writer.wait_closed()
                    await self._select()
                    self.state = 'running'
                    print('Core: running', flush=True)
                    return
                except CoreError:
                    raise
                except (OSError, ValueError, TimeoutError):
                    await asyncio.sleep(0.1)
            raise CoreError('Mihomo startup timed out')
        except BaseException as exc:
            await self._stop()
            self.state = 'failed'
            if not isinstance(exc, asyncio.CancelledError):
                detail = str(exc) if isinstance(exc, CoreError) else 'Check executable, ports and configuration'
                print('Core startup failed: ' + detail, flush=True)
            if isinstance(exc, (CoreError, asyncio.CancelledError)):
                raise
            raise CoreError('Core startup failed; check executable, ports and configuration') from None

    async def _stop(self):
        proc, self.process = self.process, None
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except (TimeoutError, asyncio.CancelledError) as exc:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                if isinstance(exc, asyncio.CancelledError):
                    raise
        self.state = 'stopped'
        if proc is not None:
            print('Core: stopped', flush=True)

    async def _idle_loop(self):
        try:
            while True:
                await asyncio.sleep(min(1, self.config['idle_seconds']))
                async with self.lock:
                    if self.process is not None and not self.active and time.monotonic() - self.last_used >= self.config['idle_seconds']:
                        await self._stop()
        except asyncio.CancelledError:
            pass

    async def close(self):
        self.closing = True
        if self.monitor:
            self.monitor.cancel()
            await self.monitor
        async with self.lock:
            await self._stop()
        shutil.rmtree(self.runtime, ignore_errors=True)
        self.lock_path.unlink(missing_ok=True)
