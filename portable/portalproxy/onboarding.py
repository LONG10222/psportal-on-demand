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
    from .core_setup import can_install
    if values.get('host_relay') == 'steam':
        return ['Steam relay uses the PC network; no subscription or Mihomo core is needed.']
    if values.get('existing_proxy_port'):
        return ['Sharing an existing client: keep that client running with its proxy enabled. StarPass does not need a separate subscription or core; verify access on the connected device.']
    notes = []
    if not source_ready(values):
        notes.append('Paste a valid HTTPS subscription, or select a local configuration in Advanced settings.')
    if not engine_ready(values):
        if values.get('engine_mode') == 'embedded':
            notes.append('Select a matching native engine in Advanced settings, or switch to external Mihomo.')
        elif can_install():
            notes.append('Mihomo is selected automatically. Start sharing prepares a missing default core; Share existing Clash reuses the running client.')
        else:
            notes.append('Select your trusted Mihomo executable, or use Share existing Clash. StarPass does not download a core automatically.')
    if not notes:
        notes.append('Import the subscription first, then click Start sharing. Starting validates the contents and chooses an available port; Internet access is not verified yet.')
    return notes


def next_step(mode, ready, devices, errors=0):
    if mode == 'accelerator':
        if not ready:
            return 'Choose the accelerator service, enable it in its own app, then start the accelerator relay. No subscription is required.'
        return 'On Android, set this Wi-Fi network HTTP proxy to the displayed PC address and port. Verify Steam store, community and text chat separately.'
    if not ready:
        from .core_setup import can_install
        return ('1. Paste once to import and save, then click Start sharing. The default Mihomo core is prepared automatically, or reuse an existing Clash client.'
                if can_install() else
                '1. Paste once to import and save, then click Start sharing. First use also needs a trusted core or an existing Clash client.')
    if type(devices) is int and devices > 0:
        if type(errors) is int and errors > 0:
            return '3. A device connected, but request errors were recorded. Check its proxy settings and the selected node. A connection is not proof of Internet access.'
        return '3. A device connected. Open the intended service on that device to verify access; this is not proof that game UDP or streaming uses the proxy.'
    if mode == 'clash':
        return '2. Configure the local app with 127.0.0.1 and the displayed port. System-wide proxying is not enabled automatically.'
    return '2. Connect the game device to the same reachable LAN, then follow LAN sharing to enter the displayed HTTP proxy address.'
