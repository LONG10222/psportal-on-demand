"""Bounded JSON IPC over the desktop child's inherited pipes; no new API port."""
import asyncio
import json

PREFIX = 'PSPORTAL_EVENT '
MAX_EVENT = 256 * 1024


def emit(event):
    line = PREFIX + json.dumps(event, ensure_ascii=False, separators=(',', ':'))
    if len(line.encode('utf-8')) <= MAX_EVENT:
        print(line, flush=True)


async def publish(proxy, core):
    counter = 0
    while True:
        snapshot = proxy.snapshot()
        snapshot['core'] = getattr(core, 'state', 'existing')
        emit(snapshot)
        if counter % 3 == 0 and hasattr(core, 'nodes') and core.state == 'running':
            try:
                emit(core.nodes.snapshot(await core.nodes.inventory()))
            except (OSError, ValueError, RuntimeError):
                pass
        counter += 1
        await asyncio.sleep(1)


async def commands(queue, core):
    while True:
        command = await queue.get()
        request_id = command.get('id')
        try:
            if not hasattr(core, 'nodes'):
                raise ValueError('Node controls are managed by the existing Clash client.')
            action = command.get('action')
            if action not in ('nodes', 'select', 'test', 'latency'):
                raise ValueError('Unknown node action')
            result = await core.nodes.command(action, command.get('group'), command.get('name'))
            result['id'] = request_id
            emit(result)
        except (OSError, ValueError, RuntimeError):
            # Do not surface URLs, credentials or raw controller responses.
            emit(dict(kind='control_error', id=request_id,
                      message='Node operation failed. Check the selected group and engine logs.'))
