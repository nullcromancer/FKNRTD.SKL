#!/usr/bin/env python3
"""Tiny Anthropic-API shim in front of LM Studio.

Claude Code >= 2.1.294 appends role:"system" messages after user turns. Several chat templates
(Qwen 3.x) raise 'System message must be at the beginning'. This shim folds every such message into
the preceding user message (prompt-cache friendly, see fix()) and forwards everything else untouched
(streaming included).

Usage: python lmstudio_shim.py [--listen 1235] [--target http://127.0.0.1:1234]
"""
import argparse
import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def as_blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)]


def fix(body: dict) -> dict:
    """Remove role:system/developer messages from the message list.

    Each one is appended, as text blocks, to the nearest preceding user message (the way Claude Code
    delivers <system-reminder> text itself). The result depends only on a message and the messages
    before it, so a request is a strict extension of the previous one and the server's prompt cache
    keeps its prefix. A system message with no user message before it goes to the top-level system field.
    Folding everything into the top-level system field instead would change that field every turn and
    force the whole conversation to be re-processed.
    """
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return body
    if not any(isinstance(m, dict) and m.get("role") in ("system", "developer") for m in msgs):
        return body
    head, kept = [], []
    for m in msgs:
        if isinstance(m, dict) and m.get("role") in ("system", "developer"):
            blocks = [{"type": "text", "text": b.get("text", "")} for b in as_blocks(m.get("content", "")) if b.get("type") == "text"]
            target = next((k for k in reversed(kept) if isinstance(k, dict) and k.get("role") == "user"), None)
            if target is None:
                head.extend(blocks)
            else:
                target["content"] = as_blocks(target.get("content", "")) + blocks
        else:
            kept.append(dict(m) if isinstance(m, dict) else m)
    if head:
        system = body.get("system")
        if system is None:
            system = []
        elif isinstance(system, str):
            system = [{"type": "text", "text": system}]
        body["system"] = list(system) + head
    body["messages"] = kept
    return body


def make_handler(target):
    t = urlparse(target)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _proxy(self):
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else b""
            if self.command == "POST" and self.path.split("?")[0].endswith("/messages") and data:
                try:
                    data = json.dumps(fix(json.loads(data))).encode()
                except ValueError:
                    pass
            conn = http.client.HTTPConnection(t.hostname, t.port or 80, timeout=3600)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length", "connection")}
            headers["Content-Length"] = str(len(data))
            try:
                conn.request(self.command, self.path, body=data, headers=headers)
                resp = conn.getresponse()
            except OSError as ex:
                msg = ("shim: upstream error: %s" % ex).encode()
                self.send_response(502); self.send_header("Content-Length", str(len(msg))); self.end_headers(); self.wfile.write(msg)
                return
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            while True:
                chunk = resp.read1(8192) if hasattr(resp, "read1") else resp.read(8192)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk); self.wfile.flush()
                except OSError:
                    break
            conn.close()

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = _proxy

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=1235)
    ap.add_argument("--target", default="http://127.0.0.1:1234")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.listen), make_handler(a.target))
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
