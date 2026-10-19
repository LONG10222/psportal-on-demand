"""Bounded private stdin/stdout control protocol; no extra network listener."""
import asyncio
import json

MAX_COMMAND_BYTES = 4096
MAX_STATUS_BYTES = 2 * 1024 * 1024
COMMANDS = frozenset(('status', 'prepare', 'test', 'select'))


def validate_command(value):
    if not isinstance(value, dict) or value.get('command') not in COMMANDS:
        raise ValueError('Unsupported runtime command')
    if set(value) - {'command', 'request_id', 'selection_mode', 'preferred_node', 'switch_threshold_ms', 'selection_group'}:
        raise ValueError('Unsupported runtime command field')
    request_id = value.get('request_id', 0)
    if type(request_id) is not int or not 0 <= request_id <= 2**31 - 1:
        raise ValueError('Invalid runtime request ID')
    group = value.get('selection_group')
    if group is not None and (not isinstance(group, str) or not 1 <= len(group.encode('utf-8')) <= 256 or any(ord(c) < 32 or ord(c) == 127 for c in group)):
        raise ValueError('Invalid profile selector group')
    if value['command'] == 'select':
        if value.get('selection_mode') not in ('auto', 'prefer', 'fixed', 'fastest'):
            raise ValueError('Invalid selection mode')
        name = value.get('preferred_node', '')
        if not isinstance(name, str) or len(name.encode('utf-8')) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise ValueError('Invalid node name')
        threshold = value.get('switch_threshold_ms', 50)
        if type(threshold) is not int or not 0 <= threshold <= 60000:
            raise ValueError('Invalid switching threshold')
    return value


def validate_legacy_command(value):
    from .nodes import valid_name
    if (not isinstance(value, dict) or value.get('action') not in ('nodes', 'select', 'test', 'latency')
            or set(value) - {'id', 'action', 'group', 'name'}
            or type(value.get('id')) is not int or not 0 <= value['id'] <= 2**31 - 1):
        raise ValueError('Unsupported node command')
    for key in ('group', 'name'):
        if value.get(key) is not None and value[key] != '' and not valid_name(value[key]):
            raise ValueError('Invalid node command name')
    if value['action'] != 'nodes' and not valid_name(value.get('group')):
        raise ValueError('Choose a proxy group')
    if value['action'] == 'select' and not valid_name(value.get('name')):
        raise ValueError('Choose a proxy node')
    return value


class RuntimeControl:
    def __init__(self, proxy, core, emit=print):
        self.proxy, self.core, self.emit = proxy, core, emit
        self.task = None
        self.last_command_id = 0
        self.command_error = ''

    def snapshot(self):
        value = self.proxy.status()
        value.update(busy=self.task is not None and not self.task.done(),
                     last_command_id=self.last_command_id, command_error=self.command_error)
        return value

    def publish(self):
        self.emit(json.dumps(self.snapshot(), ensure_ascii=False, separators=(',', ':')), flush=True)

    def accept(self, line):
        try:
            if len(line.encode('utf-8')) > MAX_COMMAND_BYTES:
                raise ValueError('Runtime command is too large')
            value = json.loads(line)
            legacy = isinstance(value, dict) and 'action' in value
            value = validate_legacy_command(value) if legacy else validate_command(value)
        except (TypeError, ValueError, RecursionError):
            self.command_error = 'Invalid runtime command'
            self.publish()
            return
        request_id = value.get('id', 0) if legacy else value.get('request_id', 0)
        if not legacy and value['command'] == 'status':
            self.publish()
            return
        if self.task is not None and not self.task.done():
            self.last_command_id, self.command_error = request_id, 'A node operation is already in progress'
            if legacy:
                emit(dict(kind='control_error', id=request_id, message=self.command_error))
            self.publish()
            return
        self.command_error = ''
        self.task = asyncio.create_task(self._run_legacy(value) if legacy else self._run(value))
        self.publish()

    async def _run(self, value):
        from .core import CoreError
        try:
            if not self.core.status().get('node_management'):
                raise CoreError('Node management is delegated to the linked proxy or imported profile')
            if value['command'] == 'prepare':
                await self.core.prepare(value.get('selection_group'))
            elif value['command'] == 'test':
                await self.core.test_nodes(value.get('selection_group'))
            else:
                await self.core.select_node(value['selection_mode'], value.get('preferred_node', ''), value.get('switch_threshold_ms'), value.get('selection_group'))
            self.command_error = ''
        except CoreError as exc:
            self.command_error = str(exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.command_error = 'Node operation failed; check the proxy engine and connectivity'
        finally:
            self.last_command_id = value.get('request_id', 0)
            self.task = None
            self.publish()

    async def _run_legacy(self, value):
        try:
            if not hasattr(self.core, 'nodes'):
                raise ValueError('Node management is delegated to the linked proxy')
            result = await self.core.nodes.command(value['action'], value.get('group'), value.get('name'))
            result['id'] = value['id']
            emit(result)
            self.command_error = ''
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, RuntimeError):
            self.command_error = 'Node operation failed. Check the selected group and engine logs.'
            emit(dict(kind='control_error', id=value['id'], message=self.command_error))
        finally:
            self.last_command_id = value['id']
            self.task = None
            self.publish()

    async def close(self):
        task = self.task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# Compatibility event records for current desktop clients.
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
                emit(core.nodes.snapshot(core.owned_inventory))
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
