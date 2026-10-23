"""Portable command-line service; does not alter OS networking or autostart."""
import argparse
import asyncio
import json
import signal
import sys
import threading
from .config import load
from .core import CoreError, CoreManager


def validate_existing_proxy(config):
    """Freshly verify saved Xianniu links; generic HTTP upstreams are unchanged."""
    if config.get('existing_proxy_provider') != 'xianniu':
        return
    port = config.get('existing_proxy_port')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Xianniu sharing requires a saved loopback proxy port. Detect and link Xianniu again.')
    from .windows_accelerator import detect_xianniu
    failure = ('Xianniu proxy verification failed. Keep Xianniu acceleration running and retry. '
               'This relay requires a verified HTTP CONNECT TCP proxy.')
    try:
        result = detect_xianniu(probe=True)
    except Exception:
        # Never print process output, client settings or exception details.
        raise ValueError(failure) from None
    if not isinstance(result, dict):
        raise ValueError(failure)
    if result.get('running') is not True:
        raise ValueError('Xianniu is not running. Open it and enable the intended acceleration, then retry.')
    endpoint = result.get('verified_endpoint')
    owners = result.get('process_ids')
    if (result.get('installed') is not True or result.get('probe_passed') is not True
            or not isinstance(endpoint, dict) or endpoint.get('host') != '127.0.0.1'
            or endpoint.get('protocol') != 'http-connect' or type(endpoint.get('port')) is not int
            or type(endpoint.get('pid')) is not int or not isinstance(owners, list)
            or endpoint['pid'] not in owners):
        raise ValueError(failure)
    if endpoint['port'] != port:
        raise ValueError('The saved Xianniu proxy port no longer matches the verified endpoint. '
                         'Detect and link Xianniu again in the desktop app; the saved port was not changed.')


async def serve(config, desktop_child=False):
    from .proxy import ProxyServer
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    def stop(*_):
        loop.call_soon_threadsafe(stopped.set)
    old = {}
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        sig = getattr(signal, name, None)
        if sig is not None:
            old[sig] = signal.signal(sig, stop)
    core = None
    proxy = None
    control = None
    publisher = None
    if desktop_child:
        from .runtime import MAX_COMMAND_BYTES
        def accept_when_ready(line):
            if control is not None:
                control.accept(line)
        def watch_parent():
            try:
                while True:
                    line = sys.stdin.readline(MAX_COMMAND_BYTES + 2)
                    if not line or line.strip() == 'stop' or len(line) > MAX_COMMAND_BYTES:
                        return
                    loop.call_soon_threadsafe(accept_when_ready, line)
            except (OSError, UnicodeError):
                pass
            finally:
                stop()
        # EOF/Stop must cancel ownership even while a fresh Xianniu capability
        # check is in flight. No listener should appear after the parent exits.
        threading.Thread(target=watch_parent, daemon=True).start()
    try:
        if config.get('existing_proxy_provider') == 'xianniu':
            await asyncio.to_thread(validate_existing_proxy, config)
            if stopped.is_set():
                return
        if config.get('existing_proxy_port'):
            from .existing_proxy import ExistingProxy
            core = ExistingProxy(config)
        else:
            core = CoreManager(config)
        proxy = ProxyServer(config, core)
        await proxy.start()
        core.start_monitor()
        if desktop_child:
            from .runtime import RuntimeControl
            control = RuntimeControl(proxy, core)
            async def publish_status():
                while True:
                    control.publish()
                    from .runtime import emit
                    snapshot = proxy.snapshot()
                    snapshot['core'] = getattr(core, 'state', 'existing')
                    emit(snapshot)
                    if hasattr(core, 'nodes') and core.state == 'running' and core.owned_inventory:
                        emit(core.nodes.snapshot(core.owned_inventory))
                    await asyncio.sleep(1)
            publisher = asyncio.create_task(publish_status())
        print(f"Proxy ready at {config['listen_host']}:{config['listen_port']}; core starts on demand", flush=True)
        await stopped.wait()
    finally:
        if publisher:
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
        if control:
            await control.close()
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
    if args.desktop_child:
        # The desktop always reads/writes UTF-8 pipes. Windows redirected
        # streams otherwise use the system code page (or PYTHONIOENCODING),
        # corrupting node names and sometimes killing the status publisher.
        # Configure before validation, diagnostics or the stdin reader thread.
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='strict')
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
