#!/usr/bin/env python3
"""Servidor HTTP que imita /api/tags, /api/ps y /api/show de Ollama."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

M = {"name": "qwen2.5-coder:14b", "size": 9_000_000_000}


class H(BaseHTTPRequestHandler):
    def _ok(self, d):
        b = json.dumps(d).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._ok({"models": [M]} if self.path in ("/api/tags", "/api/ps") else {})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._ok({"capabilities": ["completion", "tools"]})

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 11999), H).serve_forever()
