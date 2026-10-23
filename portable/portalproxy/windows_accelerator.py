"""Read-only Xianniu discovery and explicit HTTP CONNECT capability checks.

A listening socket or an HTTP 200 is not proof of a proxy. A usable endpoint
must carry a TLS handshake with normal hostname/certificate verification to a
fixed diagnostic site. Even that proves only TCP proxying, never acceleration.
No accounts, client configuration, logs, drivers or OS network settings are read.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import ntpath
import os
import re
import socket
import ssl
import subprocess
import sys
import time

MAIN_NAME = 'xianniu.exe'
HELPER_NAMES = frozenset(('socksengine.exe', 'socksenginehelper.exe', 'networktunnelx64helper.exe'))
TEST_HOSTS = ('example.com', 'www.playstation.com', 'store.steampowered.com')
MAX_CANDIDATES = 8
MAX_INVENTORY_BYTES = 65536

# Fixed inventory only. Never return command lines or read client files. An
# elevated main process may hide ExecutablePath, so keep its exact process name.
_INVENTORY_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$failures = @()
$installations = @()
$registryRoots = @(
 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')
foreach ($registryRoot in $registryRoots) {
 if (Test-Path -LiteralPath $registryRoot) {
  foreach ($entry in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
   $metadata = Get-ItemProperty -LiteralPath $entry.PSPath -ErrorAction SilentlyContinue
   if ($metadata.DisplayName -like '*鲜牛*') {
    $installations += [pscustomobject]@{
     display_name = [string]$metadata.DisplayName
     install_location = [string]$metadata.InstallLocation
     display_icon = [string]$metadata.DisplayIcon
    }
   }
  }
 }
}
$knownRoots = @()
foreach ($baseDirectory in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
 if ($baseDirectory) {
  $candidateRoot = Join-Path $baseDirectory 'xianniu'
  if (Test-Path -LiteralPath (Join-Path $candidateRoot 'XianNiuLauncher.exe') -PathType Leaf) {
   $knownRoots += $candidateRoot
  }
 }
}
$processes = @()
try {
 $processes = @(Get-CimInstance Win32_Process -Filter "Name='XianNiu.exe' OR Name='socksengine.exe' OR Name='SocksEngineHelper.exe' OR Name='networktunnelx64helper.exe'" |
  Select-Object -First 64 @{n='pid';e={[int]$_.ProcessId}}, @{n='name';e={$_.Name}}, @{n='path';e={$_.ExecutablePath}})
} catch { $failures += 'process_inventory_failed' }
$listeners = @()
$processIds = @($processes | ForEach-Object { $_.pid })
if ($processIds.Count -gt 0) {
 try {
  $listeners = @(Get-NetTCPConnection -State Listen -OwningProcess $processIds -ErrorAction Stop |
   Select-Object -First 128 @{n='pid';e={[int]$_.OwningProcess}}, @{n='host';e={$_.LocalAddress}}, @{n='port';e={[int]$_.LocalPort}})
 } catch {
  # No matches is normal; other failures are reported without exception text.
  if ($_.FullyQualifiedErrorId -notlike 'CmdletizationQuery_NotFound*') { $failures += 'listener_inventory_failed' }
 }
}
[pscustomobject]@{installations=@($installations | Select-Object -First 16); install_roots=@($knownRoots); processes=$processes; listeners=$listeners; errors=$failures} |
 ConvertTo-Json -Depth 5 -Compress
'''


def read_windows_inventory(timeout=8.0):
    """Return bounded metadata from one hidden, time-limited PowerShell call."""
    if sys.platform != 'win32':
        return {'errors': ['unsupported_platform']}
    executable = ntpath.join(os.environ.get('SystemRoot', r'C:\Windows'),
                             'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    encoded = base64.b64encode(_INVENTORY_SCRIPT.encode('utf-16-le')).decode('ascii')
    try:
        result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-WindowStyle',
                                 'Hidden', '-EncodedCommand', encoded],
                                capture_output=True, text=True, encoding='utf-8',
                                timeout=min(max(float(timeout), 0.1), 15), check=True,
                                shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000))
        if not isinstance(result.stdout, str) or len(result.stdout.encode('utf-8')) > MAX_INVENTORY_BYTES:
            return {'errors': ['invalid_inventory']}
        data = json.loads(result.stdout.lstrip('\ufeff'))
        return data if isinstance(data, dict) else {'errors': ['invalid_inventory']}
    except subprocess.TimeoutExpired:
        return {'errors': ['inventory_timeout']}
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        return {'errors': ['inventory_failed']}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


def verify_http_connect(host, port, target_host='example.com', timeout=2.0,
                        *, socket_factory=None, context_factory=None):
    """Probe an identified IPv4 loopback listener; no credentials are sent.

    Certificate validation uses the system trust store and the target hostname.
    The injectable factories are for offline transport tests. Production callers
    should use the defaults. No application data is sent after the handshake.
    """
    result = dict(probe_passed=False, tls_verified=False, acceleration_verified=False,
                  target_host=target_host, reason='invalid_endpoint')
    if (host != '127.0.0.1' or type(port) is not int or not 1024 <= port <= 65535
            or target_host not in TEST_HOSTS):
        return result
    try:
        duration = float(timeout)
        if not 0 < duration <= 10:
            return result
    except (ValueError, TypeError):
        return result
    deadline = time.monotonic() + duration
    transport = None
    encrypted = None
    try:
        connect = socket_factory or socket.create_connection
        context = (context_factory or ssl.create_default_context)()
        if context.verify_mode != ssl.CERT_REQUIRED or context.check_hostname is not True:
            result['reason'] = 'tls_verification_required'
            return result
        transport = connect((host, port), timeout=_remaining(deadline))
        authority = target_host + ':443'
        transport.settimeout(_remaining(deadline))
        transport.sendall(('CONNECT ' + authority + ' HTTP/1.1\r\nHost: ' + authority +
                           '\r\n\r\n').encode('ascii'))
        header = bytearray()
        # Do not consume/discard bytes beyond the header before TLS. In
        # particular a local HTTP control page must not be accepted as a tunnel.
        while not header.endswith(b'\r\n\r\n'):
            transport.settimeout(_remaining(deadline))
            part = transport.recv(1)
            if not part or len(header) >= 8192:
                result['reason'] = 'invalid_connect_response'
                return result
            header.extend(part)
        lines = bytes(header[:-4]).split(b'\r\n')
        if not re.fullmatch(rb'HTTP/1\.[01] 200(?: [\x20-\x7e]*)?', lines[0]):
            result['reason'] = 'connect_rejected'
            return result
        for line in lines[1:]:
            if b':' not in line or line.startswith((b' ', b'\t')):
                result['reason'] = 'invalid_connect_response'
                return result
            name, value = line.split(b':', 1)
            if (name.lower() in (b'transfer-encoding', b'upgrade')
                    or name.lower() == b'content-length' and value.strip() != b'0'):
                result['reason'] = 'http_response_is_not_tunnel'
                return result
        transport.settimeout(_remaining(deadline))
        encrypted = context.wrap_socket(transport, server_hostname=target_host,
                                         do_handshake_on_connect=False)
        encrypted.settimeout(_remaining(deadline))
        encrypted.do_handshake()
        _remaining(deadline)
        if not encrypted.getpeercert():
            result['reason'] = 'tls_certificate_missing'
            return result
        result.update(probe_passed=True, tls_verified=True, reason='connect_tls_verified')
        return result
    except (TimeoutError, socket.timeout):
        result['reason'] = 'probe_timeout'
    except ssl.SSLError:
        result['reason'] = 'tls_verification_failed'
    except (OSError, ValueError):
        result['reason'] = 'connection_failed'
    finally:
        for resource in (encrypted, transport):
            if resource is not None:
                try:
                    resource.close()
                except OSError:
                    pass
    return result


def _rows(value):
    return value if isinstance(value, list) else []


def _absolute_path(value):
    if not isinstance(value, str) or len(value) > 4096 or not ntpath.isabs(value):
        return None
    return ntpath.normcase(ntpath.normpath(value))


def _installation_roots(data):
    roots = {_absolute_path(value) for value in _rows(data.get('install_roots'))[:16]}
    for entry in _rows(data.get('installations'))[:16]:
        if not isinstance(entry, dict) or '鲜牛' not in str(entry.get('display_name', '')):
            continue
        roots.add(_absolute_path(entry.get('install_location')))
        icon = entry.get('display_icon')
        if isinstance(icon, str) and len(icon) <= 4096:
            match = re.fullmatch(r'\s*(?:"([^"\r\n]+\.exe)"|([^"\r\n]+?\.exe))(?:,\s*-?\d+)?\s*', icon, re.IGNORECASE)
            if match:
                path = _absolute_path(match.group(1) or match.group(2))
                if path and ntpath.basename(path) in ('xianniulauncher.exe', MAIN_NAME):
                    roots.add(ntpath.dirname(path))
    return sorted(root for root in roots if root)


def _under_installation(path, roots):
    for root in roots:
        try:
            if ntpath.commonpath((root, path)) == root and path != root:
                return True
        except ValueError:
            pass
    return False


def detect_xianniu(probe=False, target_host='example.com', timeout=2.0,
                   total_timeout=6.0, *, inventory=None, verifier=None):
    """Discover Xianniu, optionally verify at most eight attributed listeners.

    Call from a worker thread. `verified_endpoint` is present only after both
    CONNECT and a certificate-verified TLS handshake succeed. Helpers must have
    a readable executable path under a known Xianniu installation and an active
    main process. Wildcard and IPv6 sockets never become probe candidates.
    """
    result = dict(provider='xianniu', installed=False, running=False, process_ids=[],
                  listeners=[], candidates=[], verified_endpoint=None,
                  probe_passed=False, acceleration_verified=False, tcp_only=True,
                  capabilities=[], probe_results=[], reason='not_installed', errors=[])
    try:
        data = inventory() if callable(inventory) else inventory
        if data is None:
            data = read_windows_inventory()
    except (OSError, ValueError, subprocess.SubprocessError):
        data = {'errors': ['inventory_failed']}
    if not isinstance(data, dict):
        result.update(reason='invalid_inventory', errors=['invalid_inventory'])
        return result
    known_errors = {'unsupported_platform', 'invalid_inventory', 'inventory_failed',
                    'inventory_timeout', 'process_inventory_failed', 'listener_inventory_failed'}
    result['errors'] = [error for error in _rows(data.get('errors'))
                        if isinstance(error, str) and error in known_errors][:8]
    roots = _installation_roots(data)
    processes = [row for row in _rows(data.get('processes'))[:64]
                 if isinstance(row, dict) and type(row.get('pid')) is int and row['pid'] > 0]
    main = [row for row in processes if str(row.get('name', '')).lower() == MAIN_NAME]
    result['running'] = bool(main)
    result['installed'] = bool(roots or main or any(
        isinstance(row, dict) and '鲜牛' in str(row.get('display_name', ''))
        for row in _rows(data.get('installations'))[:16]))
    if result['errors'] and not main:
        result['reason'] = result['errors'][0]
        return result
    if not main:
        result['reason'] = 'not_running' if result['installed'] else 'not_installed'
        return result
    owned = {row['pid'] for row in main}
    for row in processes:
        name = str(row.get('name', '')).lower()
        path = _absolute_path(row.get('path'))
        if name in HELPER_NAMES and path and ntpath.basename(path) == name and _under_installation(path, roots):
            owned.add(row['pid'])
    result['process_ids'] = sorted(owned)
    seen = set()
    for row in _rows(data.get('listeners'))[:128]:
        if (not isinstance(row, dict) or type(row.get('pid')) is not int
                or row['pid'] not in owned or type(row.get('port')) is not int
                or not 1024 <= row['port'] <= 65535 or row.get('host') not in ('127.0.0.1', '0.0.0.0', '::1', '::')):
            continue
        key = row['pid'], row['host'], row['port']
        if key in seen:
            continue
        seen.add(key)
        result['listeners'].append(dict(pid=row['pid'], host=row['host'], port=row['port']))
    result['listeners'].sort(key=lambda row: (row['host'] != '127.0.0.1', row['pid'], row['port']))
    result['candidates'] = [row for row in result['listeners'] if row['host'] == '127.0.0.1'][:MAX_CANDIDATES]
    if not result['candidates']:
        result['reason'] = 'no_loopback_proxy'
        return result
    result['reason'] = 'not_probed'
    if not probe:
        return result
    try:
        if not math.isfinite(float(total_timeout)) or not math.isfinite(float(timeout)):
            raise ValueError()
        duration = min(max(float(total_timeout), 0.1), 16.0)
        per_probe = min(max(float(timeout), 0.1), 2.0)
    except (TypeError, ValueError):
        result['reason'] = 'invalid_timeout'
        return result
    deadline = time.monotonic() + duration
    check = verifier or verify_http_connect
    for endpoint in result['candidates']:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            checked = check(endpoint['host'], endpoint['port'], target_host=target_host,
                            timeout=min(per_probe, remaining))
        except (OSError, ValueError):
            checked = {'reason': 'connection_failed'}
        if not isinstance(checked, dict):
            checked = {'reason': 'invalid_probe_result'}
        passed = checked.get('probe_passed') is True and checked.get('tls_verified') is True
        result['probe_results'].append(dict(port=endpoint['port'], pid=endpoint['pid'],
                                            probe_passed=passed, reason=str(checked.get('reason', 'probe_failed'))[:80]))
        if passed and time.monotonic() <= deadline:
            result.update(verified_endpoint=dict(endpoint, protocol='http-connect'),
                          probe_passed=True, reason='connect_tls_verified',
                          capabilities=['http-connect-tcp'])
            return result
    result['reason'] = 'probe_failed'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only Xianniu proxy capability check')
    parser.add_argument('--probe', action='store_true', help='Verify CONNECT and target TLS; never starts acceleration')
    parser.add_argument('--target', choices=TEST_HOSTS, default='example.com')
    args = parser.parse_args(argv)
    print(json.dumps(detect_xianniu(probe=args.probe, target_host=args.target), ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
