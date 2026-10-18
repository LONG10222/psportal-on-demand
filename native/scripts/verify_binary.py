#!/usr/bin/env python3
"""Smoke-test an actual native executable using loopback sockets only."""
# SPDX-License-Identifier: GPL-3.0-only
import argparse
import json
import os
import pathlib
import queue
import socket
import subprocess
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def ready_line(proc):
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
    try:
        line = lines.get(timeout=10)
    except queue.Empty:
        raise AssertionError('Executable did not emit readiness within 10 seconds') from None
    return json.loads(line)


def finish(proc, *, signal=False):
    if signal:
        proc.terminate()  # SIGTERM only; Windows uses the stdin lifetime contract.
    if proc.stdin:
        proc.stdin.close()
        proc.stdin = None
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=5)
        raise AssertionError('Executable did not stop within 10 seconds') from None
    assert proc.returncode == 0, (proc.returncode, err)
    assert not err, err
    return out


def child(binary, config, port, *, requests=False, signal=False):
    proc = subprocess.Popen(
        [binary, '-config', str(config), '--desktop-child', '-status-interval', '100ms'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready = ready_line(proc)
        assert ready == {
            'event': 'ready', 'engine': 'mihomo-adapters',
            'listen_host': '127.0.0.1', 'listen_port': port,
        }, ready
        if requests:
            with socket.create_connection(('127.0.0.1', port), 2) as client:
                client.sendall(b'CONNECT 127.0.0.1:80 HTTP/1.1\r\nHost: 127.0.0.1:80\r\n\r\n')
                response = client.recv(4096)
                assert response.startswith(b'HTTP/1.1 403'), response
            with socket.create_connection(('127.0.0.1', port), 2) as client:
                client.sendall(b'GET http://8.8.8.8/ HTTP/1.1\r\nHost: example.com\r\n\r\n')
                response = client.recv(4096)
                assert response.startswith(b'HTTP/1.1 400'), response
        time.sleep(.3)
        out = finish(proc, signal=signal)
        statuses = [json.loads(line) for line in out.splitlines() if line.startswith('{')]
        assert statuses and all(s['state'] == 'stopped' and s['nodes'] == [] for s in statuses), statuses
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    args = parser.parse_args()
    binary = str(pathlib.Path(args.binary).resolve())
    version = subprocess.check_output([binary, '-version'], text=True, timeout=10)
    assert 'Mihomo 1.19.32' in version
    cfg = json.loads((ROOT / 'config.example.json').read_text(encoding='utf-8'))
    ports = set()
    while len(ports) < 3:
        ports.add(free_port())
    cfg.update(listen_host='127.0.0.1', allowed_clients=['127.0.0.1'])
    cfg['listen_port'], cfg['backend_port'], cfg['api_port'] = ports
    with tempfile.TemporaryDirectory(prefix='psportal-binary-') as tmp:
        config = pathlib.Path(tmp) / 'config.json'
        config.write_text(json.dumps(cfg), encoding='utf-8')
        subprocess.run([binary, '-config', str(config), '-check'], check=True, timeout=10)
        for _ in range(2):
            child(binary, config, cfg['listen_port'], requests=True)
        if os.name != 'nt':
            child(binary, config, cfg['listen_port'], signal=True)
        provider = pathlib.Path(tmp) / 'subscription.yaml'
        provider.write_text('proxies: [{name: fixture, type: socks5, server: 8.8.8.8, port: 1080}]', encoding='utf-8')
        cfg.pop('subscription_url')
        cfg['subscription_file'] = str(provider)
        config.write_text(json.dumps(cfg), encoding='utf-8')
        subprocess.run([binary, '-config', str(config), '-check'], check=True, timeout=10)
        child(binary, config, cfg['listen_port'])
    print('PASS: version, strict config, loopback deny, Host mismatch, cold idle, clean stop, restart, local provider config, desktop ready/EOF cleanup; no external network traffic')
    print('SIGTERM: ' + ('not applicable to Windows; graceful stdin EOF tested' if os.name == 'nt' else 'PASS'))


if __name__ == '__main__':
    main()
