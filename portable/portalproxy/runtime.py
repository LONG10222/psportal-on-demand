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
    if group is not None and (not isinstance(group, str) or not 1 <= len(group.encode('utf-8')) <= 256 or any(ord(c) < 32 for c in group)):
        raise ValueError('Invalid profile selector group')
    if value['command'] == 'select':
        if value.get('selection_mode') not in ('auto', 'prefer', 'fixed', 'fastest'):
            raise ValueError('Invalid selection mode')
        name = value.get('preferred_node', '')
        if not isinstance(name, str) or len(name.encode('utf-8')) > 256 or any(ord(c) < 32 for c in name):
            raise ValueError('Invalid node name')
        threshold = value.get('switch_threshold_ms', 50)
        if type(threshold) is not int or not 0 <= threshold <= 60000:
            raise ValueError('Invalid switching threshold')
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
            value = validate_command(json.loads(line))
        except (TypeError, ValueError, RecursionError):
            self.command_error = 'Invalid runtime command'
            self.publish()
            return
        request_id = value.get('request_id', 0)
        if value['command'] == 'status':
            self.publish()
            return
        if self.task is not None and not self.task.done():
            self.last_command_id, self.command_error = request_id, 'A node operation is already in progress'
            self.publish()
            return
        self.command_error = ''
        self.task = asyncio.create_task(self._run(value))
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

    async def close(self):
        task = self.task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
