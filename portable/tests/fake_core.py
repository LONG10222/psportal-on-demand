#!/usr/bin/env python3
"""Controlled subprocess fixture, NOT Mihomo; no Internet or subscriptions."""
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

cfg = json.loads(Path(sys.argv[sys.argv.index('-f') + 1]).read_text())
if '-t' in sys.argv:
    raise SystemExit(0)
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
            data = {'proxies':{'PORTAL':{'all':['AUTO','Tokyo','Hong Kong']}}}
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
api = http.server.ThreadingHTTPServer(('127.0.0.1', int(cfg['external-controller'].split(':')[1])), API)
socketserver.ThreadingTCPServer.allow_reuse_address = True
backend = socketserver.ThreadingTCPServer(('127.0.0.1', cfg['port']), Backend)
threading.Thread(target=backend.serve_forever, daemon=True).start()
api.serve_forever()
