"""User-initiated stable desktop updates; never execute or replace application files."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import tempfile
import time
from urllib.parse import urlsplit, unquote
import urllib.request
from .tls import verified_context

REPOSITORY = 'LONG10222/psportal-on-demand'
RELEASES_URL = f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=100'
MAX_METADATA = 4 * 1024 * 1024
MAX_PACKAGE = 2 * 1024 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 30 * 60
NAME = re.compile(r'StarPass-Desktop-(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})-(Windows|macOS|Linux)-(x64|arm64|universal)\.(zip|tar\.gz)\Z')


class UpdateError(ValueError):
    pass


@dataclass(frozen=True)
class Update:
    version: tuple[int, int, int]
    name: str
    url: str
    size: int
    sha256: str
    notes: str


def target(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    os_name = {'Windows': 'Windows', 'Darwin': 'macOS', 'Linux': 'Linux'}.get(system)
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'arm64': 'arm64', 'aarch64': 'arm64'}.get(machine)
    if not os_name or not arch:
        raise UpdateError('This system or architecture is not supported by the update channel.')
    return os_name, arch


def version_tuple(version):
    if not re.fullmatch(r'(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})', version):
        raise UpdateError('The installed desktop version is not a stable semantic version.')
    return tuple(map(int, version.split('.')))


def trusted_url(url, *, redirect=False):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.fragment:
            return False
        if p.hostname == 'github.com':
            prefix = f'/{REPOSITORY}/releases/download/'
            return p.path.startswith(prefix) and len(p.path[len(prefix):].split('/')) == 2 and not p.query and not any(x in ('.', '..') for x in unquote(p.path).split('/'))
        return redirect and p.hostname in ('release-assets.githubusercontent.com', 'objects.githubusercontent.com')
    except (ValueError, TypeError):
        return False


def select_update(releases, current, system=None, machine=None):
    current = version_tuple(current)
    os_name, arch = target(system, machine)
    if not isinstance(releases, list) or len(releases) > 100:
        raise UpdateError('Invalid release metadata.')
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') is not False or release.get('prerelease') is not False:
            continue
        assets = release.get('assets', [])
        if not isinstance(assets, list):
            raise UpdateError('Invalid release assets.')
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = asset.get('name', '')
            match = NAME.fullmatch(name) if isinstance(name, str) else None
            if not match or asset.get('state') != 'uploaded':
                continue
            major, minor, patch, asset_os, asset_arch, extension = match.groups()
            version = (int(major), int(minor), int(patch))
            if asset_os != os_name or asset_arch not in (arch, 'universal' if os_name == 'macOS' else arch):
                continue
            if extension != ('zip' if os_name == 'Windows' else 'tar.gz'):
                continue
            size, digest, url = asset.get('size'), asset.get('digest'), asset.get('browser_download_url')
            tag = release.get('tag_name')
            if (type(size) is not int or not 0 < size <= MAX_PACKAGE or not isinstance(digest, str)
                    or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest) or not trusted_url(url)
                    or not isinstance(tag, str) or not 0 < len(tag) <= 256
                    or unquote(urlsplit(url).path.split('/releases/download/', 1)[1].split('/')[0]) != tag
                    or unquote(urlsplit(url).path.rsplit('/', 1)[-1]) != name):
                raise UpdateError('A matching release package has invalid integrity metadata.')
            notes = release.get('body') or ''
            if not isinstance(notes, str):
                raise UpdateError('Invalid release notes.')
            candidates.append((version, asset_arch == arch, Update(version, name, url, size, digest[7:].lower(), notes[:4000])))
    if not candidates:
        return None, False
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = candidates[0]
    # Reject ambiguous duplicate versions rather than selecting an arbitrary payload.
    if any(v == best[0] and rank == best[1] and u != best[2] for v, rank, u in candidates[1:]):
        raise UpdateError('Conflicting packages for the same desktop version.')
    return (best[2] if best[0] > current else None), True


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl, redirect=True):
            raise UpdateError('An update redirect was blocked.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    return urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPSHandler(context=verified_context()))


def check(current, system=None, machine=None):
    request = urllib.request.Request(RELEASES_URL, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'StarPass-Desktop-Updater'})
    # The metadata endpoint must not redirect to an asset host.
    with opener().open(request, timeout=20) as response:
        if response.geturl() != RELEASES_URL:
            raise UpdateError('Unexpected release metadata destination.')
        deadline = time.monotonic() + 60
        chunks = []
        size = 0
        while size <= MAX_METADATA:
            if time.monotonic() > deadline:
                raise UpdateError('Release metadata request timed out.')
            chunk = response.read1(min(64 * 1024, MAX_METADATA + 1 - size))
            if time.monotonic() > deadline:
                raise UpdateError('Release metadata request timed out.')
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        payload = b''.join(chunks)
    if len(payload) > MAX_METADATA:
        raise UpdateError('Release metadata is too large.')
    return select_update(json.loads(payload), current, system, machine)


def download(update, destination, cancel, progress=lambda done, total: None):
    """Verify in a sibling temporary file, publish without overwriting any existing file."""
    if (not trusted_url(update.url) or type(update.size) is not int or not 0 < update.size <= MAX_PACKAGE
            or not isinstance(update.sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', update.sha256)):
        raise UpdateError('Invalid update download metadata.')
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    destination = Path(destination)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.starpass-update-', dir=destination.parent)
        with os.fdopen(fd, 'wb') as out:
            request = urllib.request.Request(update.url, headers={'User-Agent': 'StarPass-Desktop-Updater', 'Accept-Encoding': 'identity'})
            with opener().open(request, timeout=20) as response:
                if not trusted_url(response.geturl(), redirect=True):
                    raise UpdateError('Untrusted update response URL.')
                length = response.headers.get('Content-Length')
                if length is not None and (not length.isdecimal() or int(length) != update.size):
                    raise UpdateError('Update download length does not match.')
                digest = hashlib.sha256()
                count = 0
                while True:
                    if time.monotonic() > deadline:
                        raise UpdateError('Update download timed out.')
                    if cancel.is_set():
                        raise UpdateError('Update download cancelled.')
                    chunk = response.read1(128 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > update.size:
                        raise UpdateError('Update download is larger than expected.')
                    out.write(chunk)
                    digest.update(chunk)
                    progress(count, update.size)
                if count != update.size or digest.hexdigest() != update.sha256:
                    raise UpdateError('Update checksum or size verification failed.')
            out.flush()
            os.fsync(out.fileno())
        if cancel.is_set() or time.monotonic() > deadline:
            raise UpdateError('Update download cancelled or timed out.')
        os.link(temporary, destination)  # Atomic no-overwrite publication; no unpacking/execution.
        return destination
    finally:
        if temporary is not None:
            os.unlink(temporary)
