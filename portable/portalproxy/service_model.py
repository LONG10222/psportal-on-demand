"""Source configuration is independent from the game-sharing input and tabs."""
import copy
from pathlib import Path
from . import config

def owned_values(app):
    raw=copy.deepcopy(app.raw)
    saved=raw.get('accelerator_previous_config')
    if isinstance(saved,dict) and isinstance(saved.get('raw'),dict):
        raw=copy.deepcopy(saved['raw']);raw.update(saved.get('values',{}))
    elif app.product_mode()!='accelerator':
        for key,var in app.vars.items():
            if key in config.DEFAULTS and type(config.DEFAULTS[key]) is int:
                try:raw[key]=int(var.get())
                except ValueError:raise ValueError('参数无效：'+key) from None
            elif key in ('core_path','native_path','engine_mode','profile_file','subscription_file','subscription_url','selection_mode','preferred_node'):
                raw[key]=var.get().strip()
    previous=raw.get('linked_previous_source')
    if raw.get('existing_proxy_port') and isinstance(previous,dict):raw.update(copy.deepcopy(previous))
    for key in ('existing_proxy_port','existing_proxy_provider','host_relay','accelerator_proxy','linked_previous_source','accelerator_previous_config','shared_core','local_proxy_port'):
        raw.pop(key,None)
    for key,default in config.DEFAULTS.items():
        if type(default) is int and isinstance(raw.get(key),str):
            try:raw[key]=int(raw[key])
            except ValueError:raise ValueError('配置参数无效') from None
    if not (raw.get('profile_file') or raw.get('subscription_file')):raise ValueError('请先导入独立订阅')
    raw.update(product_mode='clash',listen_host='127.0.0.1',allowed_clients=['127.0.0.1'])
    return raw

def source_descriptor(values, identity):
    from .subscription_monitor import descriptor
    from .desktop import reusable_source
    import json
    path=values.get('profile_file') or values.get('subscription_file') or ''
    cache=None
    try:
        sidecar=Path(path).with_suffix(Path(path).suffix+'.info.json')
        if sidecar.is_file() and sidecar.stat().st_size<=8192:cache=json.loads(sidecar.read_text(encoding='utf-8'))
    except (OSError,ValueError):pass
    origin=values.get('source_provenance',{})
    url=origin.get('url','') if isinstance(origin,dict) and origin.get('kind')=='subscription' and reusable_source(values,path,origin.get('url','')) else ''
    return descriptor(url,cache,identity=identity+':'+path)
