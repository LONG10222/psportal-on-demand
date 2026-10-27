"""Owned Mihomo lifecycle. Never attaches to or terminates an unrelated core."""
import asyncio
import copy
import json
import http.client
import ssl
import queue
import threading
from urllib.parse import urlsplit, quote, urlencode
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


def download_subscription(url, destination, *, headers_only=False):
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
        from .tls import verified_context
        connection = PinnedHTTPS(host, port, timeout=5, context=verified_context())
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        connection.request('HEAD' if headers_only else 'GET', path, headers={'User-Agent':'clash.meta/1.19.32 PSPortal-OnDemand/0.1', 'Accept-Encoding':'identity'})
        response = connection.getresponse()
        if headers_only:
            from .subscription_info import from_headers
            info=from_headers(response.headers,url)
            if response.status in (405,501) or response.status==200 and not any(k in info for k in ('upload','download','total','expire')):
                # Some providers expose accounting only on GET. Request just
                # the headers, retain the same pinned TLS policy and deadline,
                # and close without downloading/parsing a second profile.
                response.close();connection.close()
                connection=PinnedHTTPS(host,port,timeout=5,context=verified_context())
                connection.request('GET',path,headers={'User-Agent':'clash.meta/1.19.32 PSPortal-OnDemand/0.1','Accept-Encoding':'identity'})
                response=connection.getresponse()
            if response.status!=200:raise CoreError('Subscription accounting unavailable')
            return from_headers(response.headers,url)
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
        root = Path(config['data_dir']).expanduser().resolve()
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
        self.node_rows = []
        from .nodes import NodeControl
        self.nodes = NodeControl(self)
        self.node_paths = {}
        self.owned_inventory = {}
        self.ambiguous_nodes = set()
        self.groups = []
        self.selection_group = ''
        self.profile_mode = 'profile'
        self.profile_groups = None
        self.selected = ''
        self.selector_choice = ''
        self.last_error = ''
        self.preparing = False
        self.last_health = 0.0
        self.startup_deadline = None
        self.probe_complete = False
        self.probe_tested = 0
        self.probe_total = 0
        from .policy import FastestSelection
        self.fastest = FastestSelection()

    def start_monitor(self):
        if self.monitor is None:
            self.monitor = asyncio.create_task(self._idle_loop())

    def _request(self, path, method='GET', payload=None, timeout=2):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(f"http://127.0.0.1:{self.config['api_port']}{path}",
            data=None if payload is None else json.dumps(payload).encode(), method=method,
            headers={'Authorization':'Bearer '+self.secret, 'Content-Type':'application/json'})
        with opener.open(request, timeout=timeout) as response:
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise CoreError('Controller response too large')
            return json.loads(data) if data else {}

    @property
    def node_management(self):
        return True  # This manager owns its controller; linked proxies use ExistingProxy.

    @property
    def selection_mode(self):
        return self.profile_mode if self.config.get('profile_file') else self.config['selection_mode']

    def status(self):
        return {'core_state': self.state, 'selected_node': self.selected,
                'nodes': [dict(node) for node in self.node_rows],
                'node_policies': dict(self.nodes.policies),
                'selection_mode': self.selection_mode,
                'selection_group': self.selection_group,
                'groups': [{'name': group['name'], 'selected': group['selected'], 'eligible_node_count': len(group['members'])} for group in self.groups],
                'switch_threshold_ms': self.config.get('switch_threshold_ms', 50),
                'node_management': self.node_management, 'error': self.last_error,
                'preparing': self.preparing, 'probe_complete': self.probe_complete,
                'probe_tested': self.probe_tested, 'probe_total': self.probe_total}

    @staticmethod
    def _safe_name(name):
        return (isinstance(name, str) and 1 <= len(name.encode('utf-8')) <= 256
                and not any(ord(c) < 32 or ord(c) == 127 for c in name))

    async def _refresh_nodes(self, selection_group=None):
        result = await asyncio.to_thread(self._request, '/proxies')
        proxies = result.get('proxies', {})
        if not isinstance(proxies, dict):
            raise CoreError('Invalid owned controller node inventory')
        proxies = dict(proxies)
        global_names = set(proxies)
        paths = {name: '/proxies/' + quote(name, safe='') + '/delay' for name in global_names if self._safe_name(name)}
        # Provider adapters are not addressable through /proxies/{name}/delay.
        # Resolve their exact owned provider before testing, including imported
        # profiles with more than one subscription provider.
        provider_result = await asyncio.to_thread(self._request, '/providers/proxies')
        providers = provider_result.get('providers', {})
        ambiguous = set()
        if not isinstance(providers, dict):
            raise CoreError('Invalid owned provider inventory')
        for provider, data in providers.items():
            if not self._safe_name(provider) or not isinstance(data, dict):
                continue
            items = data.get('proxies', [])
            if not isinstance(items, list):
                continue
            for item in items[:1000]:
                name = item.get('name') if isinstance(item, dict) else None
                if not self._safe_name(name) or name in global_names:
                    continue
                if name in paths:
                    ambiguous.add(name)
                    continue
                proxies[name] = item
                paths[name] = '/providers/proxies/' + quote(provider, safe='') + '/' + quote(name, safe='') + '/healthcheck'
        self.node_paths = paths
        self.owned_inventory = proxies
        self.ambiguous_nodes = ambiguous
        def eligible(name):
            if not self._safe_name(name) or name in ambiguous or name in ('PORTAL', 'PORTAL-AUTO', 'REJECT', 'DIRECT', 'AUTO'):
                return False
            item = proxies.get(name, {})
            kind = item.get('type') if isinstance(item, dict) else None
            # The external core already validated its adapter graph. Preserve
            # all genuine leaf protocols, including newer Mihomo adapters;
            # only routing groups and direct/bypass actions are ineligible.
            return (isinstance(kind, str) and bool(kind) and len(kind) <= 64
                    and item.get('all') is None and kind.lower() not in
                    ('direct','reject','rejectdrop','compatible','pass','passrule','rematch','dns',
                     'relay','selector','select','fallback','urltest','url-test','loadbalance','load-balance'))
        group_name = 'PORTAL'
        if self.config.get('profile_file'):
            groups = []
            for name, item in proxies.items():
                if (not self._safe_name(name) or name == 'GLOBAL' or not isinstance(item, dict)
                        or (self.profile_groups is not None and name not in self.profile_groups)
                        or str(item.get('type', '')).lower() not in ('selector', 'select', 'fallback', 'urltest', 'url-test')
                        or not isinstance(item.get('all'), list)):
                    continue
                members = [member for member in item['all'] if eligible(member)][:1000]
                if members:
                    selected = item.get('now', '')
                    groups.append({'name': name, 'selected': selected if self._safe_name(selected) else '', 'members': members})
            self.groups = groups[:1000]
            group_names = {group['name'] for group in self.groups}
            if selection_group is not None:
                if selection_group not in group_names:
                    raise CoreError('Select an owned profile selector group with eligible proxy nodes')
                if selection_group != self.selection_group:
                    self.selection_group = selection_group
                    policy = self.nodes.policies.get(selection_group, {})
                    self.profile_mode = {'manual': 'fixed', 'latency': 'fastest'}.get(policy.get('mode'), 'profile')
                    if policy.get('mode') == 'manual':
                        self.config['preferred_node'] = policy['name']
                    from .policy import FastestSelection
                    self.fastest = self.nodes.fastest.setdefault(selection_group, FastestSelection())
            if self.selection_group and self.selection_group not in group_names:
                self.selection_group, self.profile_mode = '', 'profile'
                raise CoreError('Selected profile group is no longer available')
            if not self.selection_group:
                self.node_rows, self.selected = [], ''
                return
            group_name = self.selection_group
        elif selection_group not in (None, '', 'PORTAL'):
            raise CoreError('Subscription nodes use the owned PORTAL group')
        group = proxies.get(group_name, {})
        names = group.get('all', [])
        if not isinstance(names, list):
            raise CoreError('Owned selector group is unavailable')
        old = {n['name']: n for n in self.node_rows}
        nodes = []
        seen = set()
        for name in names[:1003]:
            if not eligible(name) or name in seen:
                continue
            seen.add(name)
            item = proxies.get(name, {})
            previous = old.get(name, {})
            history = item.get('history', [])
            delay = history[-1].get('delay') if isinstance(history, list) and history and isinstance(history[-1], dict) else previous.get('delay_ms')
            alive = item.get('alive', previous.get('healthy'))
            alive = alive if type(alive) is bool else None
            delay = delay if type(delay) in (int, float) and 0 <= delay <= 86400000 and alive is not False else None
            nodes.append({'name': name, 'healthy': alive, 'delay_ms': delay, 'type': str(item.get('type', ''))[:64]})
        self.node_rows = nodes[:1000]
        selected = group.get('now', self.selected)
        choice = group.get('fixed') or selected
        self.selector_choice = choice if self._safe_name(choice) else ''
        if selected == 'PORTAL-AUTO' and not self.config.get('profile_file'):
            selected = proxies.get('PORTAL-AUTO', {}).get('now', '')
        self.selected = selected if selected in {n['name'] for n in self.node_rows} else ''

    def _record_selection(self, name, actual=None):
        actual = name if actual is None else actual
        group = self.selection_group if self.config.get('profile_file') else 'PORTAL'
        if group in self.owned_inventory:
            self.owned_inventory[group]['now'] = actual
            if 'fixed' in self.owned_inventory[group]:
                self.owned_inventory[group]['fixed'] = name
        self.selector_choice = name
        self.selected = actual if actual in {n['name'] for n in self.node_rows} else ''
        for item in self.groups:
            if item['name'] == self.selection_group:
                item['selected'] = actual

    async def _restore_choice(self, name, clear_override=False):
        group = self.selection_group if self.config.get('profile_file') else 'PORTAL'
        if not group or not self._safe_name(name):
            self._record_selection('')
            return False
        path = '/proxies/' + quote(group, safe='')
        try:
            if clear_override:
                await asyncio.to_thread(self._request, path, 'DELETE')
            else:
                await asyncio.to_thread(self._request, path, 'PUT', {'name': name})
            actual = await asyncio.to_thread(self._request, path)
            if clear_override:
                if actual.get('fixed') != '':
                    raise CoreError('Previous group policy could not be restored')
            elif actual.get('fixed', actual.get('now')) != name and actual.get('now') != name:
                raise CoreError('Previous node selection could not be restored')
            self._record_selection(name, actual.get('now', name))
            if clear_override and group in self.owned_inventory:
                self.owned_inventory[group]['fixed'] = ''
            return True
        except (OSError, ValueError, CoreError):
            self._record_selection('')
            self.last_error = 'Node selection is unverified; refresh live nodes before retrying'
            return False

    async def _put_selection(self, name):
        group = self.selection_group if self.config.get('profile_file') else 'PORTAL'
        if not group:
            raise CoreError('Choose a profile selector group first')
        if self.config.get('profile_file') and not any(g['name'] == group and name in g['members'] for g in self.groups):
            raise CoreError('Node is not an eligible member of the selected profile group')
        path = '/proxies/' + quote(group, safe='')
        previous = await asyncio.to_thread(self._request, path)
        clear_override = 'fixed' in previous and not previous['fixed']
        previous = previous.get('fixed') or previous.get('now')
        if not self._safe_name(previous):
            raise CoreError('Current node selection could not be verified')
        try:
            await asyncio.to_thread(self._request, path, 'PUT', {'name': name})
            verified = await asyncio.to_thread(self._request, path)
            if verified.get('fixed', verified.get('now')) != name and verified.get('now') != name:
                raise CoreError('Node selection could not be verified')
        except asyncio.CancelledError:
            self._record_selection('')
            raise
        except (OSError, ValueError, CoreError):
            restored = await self._restore_choice(previous, clear_override=clear_override)
            raise CoreError('Node selection failed; previous choice restored' if restored else
                            'Node selection is unverified; refresh live nodes before retrying') from None
        self._record_selection(name, verified.get('now', name))

    async def _apply_policy(self, *, measured=False, stable_round=True, candidates=None):
        mode = self.selection_mode
        preferred = self.config['preferred_node']
        names = {n['name'] for n in self.node_rows}
        if mode == 'profile':
            return  # Preserve the complete profile's own graph until explicitly selected.
        if mode == 'fixed':
            if preferred not in names:
                raise CoreError('Fixed node is missing from the subscription')
            await self._put_selection(preferred)
        elif mode == 'fastest':
            if measured:
                old_fastest = copy.deepcopy(self.fastest)
                chosen = self.fastest.choose(self.node_rows if candidates is None else candidates, self.config.get('switch_threshold_ms', 50), measured=stable_round)
                try:
                    if chosen or not self.config.get('profile_file'):
                        await self._put_selection(chosen or 'REJECT')
                except BaseException:
                    self.fastest = old_fastest
                    raise
                if not chosen:
                    raise CoreError('No healthy proxy node is available')
        elif mode == 'prefer' and any(n['name'] == preferred and n.get('healthy') is True for n in self.node_rows):
            await self._put_selection(preferred)
        else:
            await self._put_selection('PORTAL-AUTO')

    async def _probe_nodes(self, budget=None):
        sem = asyncio.Semaphore(8)
        timeout_ms = min(32767, self.config['health_timeout'])
        async def probe(node):
            async with sem:
                path = self.node_paths.get(node['name'], '/proxies/' + quote(node['name'], safe='') + '/delay') + '?' + urlencode(
                    {'url': self.config['health_url'], 'timeout': timeout_ms, 'expected': '204'})
                try:
                    result = await asyncio.to_thread(self._request, path, 'GET', None, timeout_ms / 1000 + 1)
                    delay = result.get('delay')
                    ok = type(delay) in (int, float) and 0 <= delay <= timeout_ms
                except (OSError, ValueError, CoreError):
                    delay, ok = None, False
                return node, ok, delay if ok else None
        budget = self.config['wakeup_timeout'] if budget is None else budget
        if self.state == 'starting' and self.startup_deadline is not None:
            budget = max(.001, min(budget, self.startup_deadline - time.monotonic() - .25))
        tasks = [asyncio.create_task(probe(node)) for node in self.node_rows]
        if not tasks:
            self.probe_complete, self.probe_tested, self.probe_total = True, 0, 0
            await self._apply_policy(measured=True)
            return
        try:
            done, pending = await asyncio.wait(tasks, timeout=budget)
        except asyncio.CancelledError:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise  # Stop/stale cancellation never publishes a partial batch.
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        results = [task.result() for task in done if not task.cancelled()]
        for node, healthy, delay in results:
            node.update(healthy=healthy, delay_ms=delay)
        self.probe_complete = not pending
        self.probe_tested, self.probe_total = len(results), len(tasks)
        self.last_health = time.monotonic()
        # A deadline may still yield useful healthy measurements. Keep a known
        # incumbent, but only fresh completed nodes can challenge/fail over.
        completed = {node['name'] for node, _, _ in results}
        candidates = [node for node in self.node_rows if node['name'] in completed or node['name'] == self.fastest.current]
        await self._apply_policy(measured=True, stable_round=not pending, candidates=candidates)

    async def _select(self):
        # Reapply saved provider intent before the first startup selection.
        # This also makes fastest perform its measured probe on every wake.
        self.nodes.restore_provider_policy()
        await self._refresh_nodes()
        if self.selection_mode == 'fastest':
            await self._probe_nodes()
        else:
            await self._apply_policy()

    def _require_nodes(self):
        if self.closing:
            raise CoreError('Proxy is stopping')

    async def prepare(self, selection_group=None):
        self._require_nodes()
        self.preparing = True
        already_running = self.process is not None and self.process.returncode is None
        previous_group = self.selection_group
        try:
            await self.acquire()
            try:
                async with self.lock:
                    await self._refresh_nodes(selection_group)
                    if self.node_rows and (already_running or self.selection_mode != 'fastest' or previous_group != self.selection_group):
                        await self._probe_nodes()
                    self.last_error = ''
            finally:
                await self.release()
        finally:
            self.preparing = False

    async def test_nodes(self, selection_group=None):
        if self.config.get('profile_file') and not (selection_group or self.selection_group):
            raise CoreError('Choose a profile selector group before testing nodes')
        await self.prepare(selection_group)

    async def select_node(self, mode, name='', switch_threshold_ms=None, selection_group=None):
        self._require_nodes()
        if self.config.get('profile_file') and mode not in ('fixed', 'fastest'):
            raise CoreError('Owned profile groups support explicit manual or fastest selection')
        if mode not in ('auto', 'prefer', 'fixed', 'fastest'):
            raise CoreError('Unsupported selection mode')
        if not isinstance(name, str) or len(name.encode('utf-8')) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise CoreError('Invalid node name')
        if switch_threshold_ms is not None and (type(switch_threshold_ms) is not int or not 0 <= switch_threshold_ms <= 60000):
            raise CoreError('Invalid switching threshold')
        target_group = selection_group or self.selection_group or 'PORTAL'
        if mode in ('fixed', 'fastest') and target_group not in self.nodes.policies and len(self.nodes.policies) >= 32:
            raise CoreError('At most 32 group policies can be saved')
        await self.acquire()
        try:
            async with self.lock:
                # Capture policy before a group refresh can change its scope.
                old = (self.selection_group, self.profile_mode,
                       self.config['selection_mode'], self.config['preferred_node'],
                       self.config.get('switch_threshold_ms', 50), copy.deepcopy(self.fastest))
                previous_choice = ''
                try:
                    await self._refresh_nodes(selection_group)
                    previous_choice = self.selector_choice
                    if self.config.get('profile_file') and not self.selection_group:
                        raise CoreError('Choose a profile selector group first')
                    if mode in ('fixed', 'prefer') and name not in {n['name'] for n in self.node_rows}:
                        raise CoreError('Selected node is missing from the subscription')
                    if self.config.get('profile_file'):
                        self.profile_mode = mode
                    self.config['selection_mode'], self.config['preferred_node'] = mode, name if mode in ('fixed', 'prefer') else ''
                    if switch_threshold_ms is not None:
                        self.config['switch_threshold_ms'] = switch_threshold_ms
                    if mode == 'fastest':
                        target_group = self.selection_group if self.config.get('profile_file') else 'PORTAL'
                        if self.nodes.policies.get(target_group, {}).get('mode') != 'latency':
                            from .policy import FastestSelection
                            self.fastest = FastestSelection()
                        await self._probe_nodes()
                    else:
                        await self._apply_policy()
                    target_group = self.selection_group if self.config.get('profile_file') else 'PORTAL'
                    self.nodes.save_policy(target_group, mode, name)
                    self.nodes.fastest[target_group] = self.fastest
                    if mode == 'fastest':
                        self.nodes.last_test[target_group] = time.monotonic()
                    self.last_error = ''
                except BaseException as exc:
                    # Restore the exact previously verified member of the target
                    # group, including an existing nested profile policy.
                    cancelled = isinstance(exc, asyncio.CancelledError)
                    if not cancelled and not self.closing and previous_choice and self.selector_choice != previous_choice:
                        await self._restore_choice(previous_choice)
                    (self.selection_group, self.profile_mode, self.config['selection_mode'],
                     self.config['preferred_node'], self.config['switch_threshold_ms'], self.fastest) = old
                    try:
                        if cancelled:
                            self._record_selection('')
                        else:
                            await self._refresh_nodes()
                    except (OSError, ValueError, CoreError):
                        self._record_selection('')
                        self.last_error = 'Node selection is unverified; refresh live nodes before retrying'
                    raise
        finally:
            await self.release()

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
        self.startup_deadline = time.monotonic() + self.config['wakeup_timeout']
        self.last_error = ''
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
            if not self.config.get('profile_file'):
                from .profiles import read_profile
                provider_path = self.runtime / 'providers/subscription.yaml'
                canonical = read_profile(provider_path)
                atomic_private(provider_path, json.dumps(canonical, ensure_ascii=False).encode())
            rendered = generated if self.config.get('profile_file') else render(self.config, self.secret)
            if self.config.get('profile_file'):
                self.profile_groups = {group.get('name') for group in rendered.get('proxy-groups', []) if group.get('type') in ('select', 'fallback', 'url-test')}
            atomic_private(self.runtime / 'config.json', json.dumps(rendered, ensure_ascii=False).encode('utf-8'))
            args = (str(Path(self.config['core_path']).expanduser().resolve()), '-d', str(self.runtime), '-f', str(self.runtime / 'config.json'))
            check = await launch_external(*args, '-t')
            try:
                result = await asyncio.wait_for(check.wait(), timeout=self.config['wakeup_timeout'])
            finally:
                if check.returncode is None:
                    check.kill()
                    await check.wait()
            if result:
                raise CoreError('Mihomo rejected the generated configuration or subscription')
            # Mihomo opens its controller/listener before tunnel.OnRunning.
            # Its official post-up hook runs only after ApplyConfig completes.
            # No user text or paths enter this fixed shell command: private cwd,
            # constant filename and a fresh hexadecimal nonce are the entire input.
            ready_path = self.runtime / 'psportal-ready'
            ready_path.unlink(missing_ok=True)
            ready_nonce = secrets.token_hex(32).encode('ascii')
            self.process = await launch_external(*args, '-post-up',
                'echo ' + ready_nonce.decode('ascii') + '>psportal-ready', cwd=self.runtime)
            deadline = time.monotonic() + self.config['wakeup_timeout']
            while time.monotonic() < deadline:
                if self.process.returncode is not None:
                    raise CoreError('Mihomo exited during startup; use a core with -post-up readiness support (tested with v1.19.32)')
                try:
                    try:
                        with ready_path.open('rb') as ready:
                            marker = ready.read(81)
                    except FileNotFoundError:
                        marker = b''
                    if len(marker) > 80 or marker.strip() != ready_nonce:
                        await asyncio.sleep(0.05)
                        continue
                    await asyncio.to_thread(self._request, '/version')
                    reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1', self.config['backend_port']), timeout=1)
                    writer.close()
                    await writer.wait_closed()
                    await self._select()
                    await self.nodes.restore()
                    self.state = 'running'
                    self.startup_deadline = None
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
                self.last_error = detail
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
        self.startup_deadline = None
        self.selected = ''
        self.selector_choice = ''
        from .policy import FastestSelection
        self.fastest = FastestSelection()
        if proc is not None:
            print('Core: stopped', flush=True)

    async def _idle_loop(self):
        try:
            while True:
                await asyncio.sleep(min(1, self.config['idle_seconds']))
                async with self.lock:
                    if self.process is None:
                        continue
                    if self.process.returncode is not None:
                        self.state, self.last_error = 'failed', 'Owned proxy engine exited unexpectedly'
                        continue
                    if not self.active and time.monotonic() - self.last_used >= self.config['idle_seconds']:
                        await self._stop()
                        continue
                    try:
                        await self._refresh_nodes()
                        if self.node_management and self.selection_mode == 'fastest' and not self.nodes.policies and time.monotonic() - self.last_health >= max(30, self.config['health_interval']):
                            await self._probe_nodes()
                            self.last_error = ''
                        elif self.node_management and self.selection_mode == 'prefer':
                            await self._apply_policy()
                    except (OSError, ValueError, CoreError, TimeoutError):
                        self.last_error = 'Node status or health check failed'
                if self.state == 'running':
                    await self.nodes.tick()
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
