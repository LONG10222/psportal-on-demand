"""Read-only beginner guidance. Never probes the Internet or changes settings."""
from pathlib import Path
from urllib.parse import urlsplit


def source_ready(values):
    for key in ('profile_file', 'subscription_file'):
        value = values.get(key, '')
        if value:
            try:
                if Path(value).expanduser().is_file():
                    return True
            except (OSError, ValueError):
                pass
    try:
        value = values.get('subscription_url', '').strip()
        url = urlsplit(value)
        return bool(url.scheme == 'https' and url.hostname and not url.username
                    and not url.password and not url.fragment and url.hostname.isascii()
                    and not any(ord(c) <= 32 for c in value)
                    and not any(c in url.netloc for c in '\\%')
                    and (url.port is None or 1 <= url.port <= 65535))
    except (ValueError, TypeError, AttributeError):
        return False


def engine_ready(values):
    key = 'native_path' if values.get('engine_mode') == 'embedded' else 'core_path'
    try:
        path = Path(values.get(key, '')).expanduser()
        return path.is_absolute() and path.is_file()
    except (OSError, ValueError, TypeError):
        return False


def preparation_notes(values):
    """Fixed messages only: never echo a secret URL, path or exception."""
    if values.get('existing_proxy_port'):
        return ['Sharing an existing client: keep that client running with its proxy enabled. StarPass does not need a separate subscription or core; verify access on the connected device.']
    notes = []
    if not source_ready(values):
        notes.append('Paste a valid HTTPS subscription, or select a local configuration in Advanced settings.')
    if not engine_ready(values):
        notes.append('Select your trusted Mihomo executable, or use Share existing Clash. StarPass does not download a core automatically.'
                     if values.get('engine_mode') != 'embedded' else
                     'Select a matching native engine in Advanced settings, or switch to external Mihomo.')
    if not notes:
        notes.append('Subscription and engine paths are present. Prepare & start will validate the contents and choose an available port; Internet access is not verified yet.')
    return notes


def next_step(mode, ready, devices, errors=0):
    if not ready:
        return '1. Prepare the service: paste a subscription and click Prepare & start. First use also needs a trusted core or an existing Clash client.'
    if type(devices) is int and devices > 0:
        if type(errors) is int and errors > 0:
            return '3. A device connected, but request errors were recorded. Check its proxy settings and the selected node. A connection is not proof of Internet access.'
        return '3. A device connected. Open the intended service on that device to verify access; this is not proof that game UDP or streaming uses the proxy.'
    if mode == 'clash':
        return '2. Configure the local app with 127.0.0.1 and the displayed port. System-wide proxying is not enabled automatically.'
    return '2. Connect the game device to the same reachable LAN, then follow LAN sharing to enter the displayed HTTP proxy address.'
