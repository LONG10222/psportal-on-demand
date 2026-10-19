#!/usr/bin/env python3
"""Controlled subprocess fixture, NOT Mihomo; no Internet or subscriptions."""
import http.server
import json
import os
import re
import time
import socketserver
import sys
import threading
from pathlib import Path

cfg = None
name = 'AUTO'
class API(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer '+cfg['secret']:
            self.send_error(401)
            return
        data = {'version':'fixture'}
        if self.path == '/proxies':
            data = {'proxies':{'PORTAL':{'type':'Selector','all':['PORTAL-AUTO','Tokyo','Hong Kong'],'now':name}, 'PORTAL-AUTO':{'type':'Fallback','all':['Tokyo','Hong Kong'],'now':'Hong Kong'}, 'Tokyo':{'type':'Http','alive':True}, 'Hong Kong':{'type':'Http','alive':True}}}
        elif self.path == '/proxies/PORTAL':
            data = {'now':name}
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def do_PUT(self):
        global name
        if self.headers.get('Authorization') != 'Bearer '+cfg['secret']:
            self.send_error(401)
            return
        name = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['name']
        self.send_response(204)
        self.end_headers()
class Backend(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(65536)
        self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\nfixture')
class FixtureHTTPServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's default performs reverse DNS for server_name. This
        # controlled loopback fixture must not depend on runner DNS latency.
        socketserver.TCPServer.server_bind(self)
        self.server_name = 'offline-fixture'
        self.server_port = self.server_address[1]

def main():
    global cfg
    cfg = json.loads(Path(sys.argv[sys.argv.index('-f') + 1]).read_text())
    if '-t' in sys.argv:
        return
    api = FixtureHTTPServer(('127.0.0.1', int(cfg['external-controller'].split(':')[1])), API)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    backend = socketserver.ThreadingTCPServer(('127.0.0.1', cfg['port']), Backend)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    def mark_ready():
        if '-post-up' not in sys.argv:
            return
        command = sys.argv[sys.argv.index('-post-up') + 1]
        match = re.fullmatch(r'echo ([0-9a-f]{64})>psportal-ready', command)
        if not match:
            raise ValueError('Unsupported fixture startup hook')
        mode = os.environ.get('PSPORTAL_FIXTURE_READY_MODE', '')
        if mode == 'missing':
            return
        time.sleep(float(os.environ.get('PSPORTAL_FIXTURE_READY_DELAY', '0')))
        # Simulate Windows CRLF without invoking a shell in this test fixture.
        nonce = '0' * 64 if mode == 'stale' else match.group(1)
        Path('psportal-ready').write_bytes(nonce.encode('ascii') + b'\r\n')
    threading.Thread(target=mark_ready, daemon=True).start()
    api.serve_forever()


if __name__ == '__main__':
    main()
