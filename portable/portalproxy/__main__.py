"""Portable command-line service; does not alter OS networking or autostart."""
import argparse
import asyncio
import json
import signal
import sys
import threading
from .config import load
from .core import CoreError, CoreManager


async def serve(config, desktop_child=False):
    from .proxy import ProxyServer
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    def stop(*_):
        loop.call_soon_threadsafe(stopped.set)
    old = {}
    commands = asyncio.Queue(maxsize=16)
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        sig = getattr(signal, name, None)
        if sig is not None:
            old[sig] = signal.signal(sig, stop)
    if desktop_child:
        def enqueue(command):
            if not commands.full():
                commands.put_nowait(command)
        def watch_parent():
            while True:
                line = sys.stdin.readline(8193)
                if not line:
                    break
                if len(line) > 8192:
                    while line and not line.endswith('\n'):
                        line = sys.stdin.readline(8193)
                    continue
                if line.strip() == 'stop':
                    break
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and type(value.get('id')) is int:
                        loop.call_soon_threadsafe(enqueue, value)
                except ValueError:
                    pass
            stop()
        threading.Thread(target=watch_parent, daemon=True).start()
    core = None
    proxy = None
    ipc_tasks = []
    try:
        if config.get('existing_proxy_port'):
            from .existing_proxy import ExistingProxy
            core = ExistingProxy(config)
        else:
            core = CoreManager(config)
        proxy = ProxyServer(config, core)
        await proxy.start()
        core.start_monitor()
        print(f"Proxy ready at {config['listen_host']}:{config['listen_port']}; core starts on demand", flush=True)
        if desktop_child:
            from . import runtime
            ipc_tasks = [asyncio.create_task(runtime.publish(proxy, core)),
                         asyncio.create_task(runtime.commands(commands, core))]
        await stopped.wait()
    finally:
        for task in ipc_tasks:
            task.cancel()
        if ipc_tasks:
            await asyncio.gather(*ipc_tasks, return_exceptions=True)
        if proxy:
            await proxy.close()
        if core:
            await core.close()
        for sig, handler in old.items():
            signal.signal(sig, handler)
        print('Proxy stopped', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='PS Portal on-demand LAN HTTP proxy')
    parser.add_argument('--config', required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--desktop-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        if config['engine_mode'] == 'embedded':
            from pathlib import Path
            from .backend import run_native
            return run_native(Path(args.config), config, check=args.check, desktop_child=args.desktop_child)
        if args.check:
            print('Configuration is valid.', flush=True)
            return 0
        asyncio.run(serve(config, args.desktop_child))
        return 0
    except (ValueError, CoreError) as exc:
        print('Error: ' + str(exc), file=sys.stderr, flush=True)
        return 1
    except OSError:
        print('Error: Unable to access configuration, bind listener or run core; check paths and permissions.', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
