"""Local development launcher; uses the isolated runtime prepared on this Mac."""
import json
import os
from pathlib import Path
import sys

repo = Path(__file__).resolve().parent
work = repo.parent.parent / 'work'
private = repo / 'config.local'
private.mkdir(mode=0o700, exist_ok=True)
path = private / 'desktop.json'
if not path.exists():
    initial = dict(listen_host='', allowed_clients=[], subscription_url='',
                   core_path=str(work / 'desktop-cores/mihomo'),
                   native_path=str(work / 'desktop-cores/psportal-native'), engine_mode='external')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(initial, stream, ensure_ascii=False, indent=2)
    preference = path.with_name(path.name + '.ui.json')
    fd = os.open(preference, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump({'language': 'zh'}, stream)
sys.path.insert(0, str(repo / 'portable'))
from portalproxy.desktop import main
raise SystemExit(main(['--config', str(path)]))
