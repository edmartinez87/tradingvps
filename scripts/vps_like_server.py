"""Serves a production frontend build like the VPS Caddy does (static + SPA fallback + /api → backend:8001). QA only.
Usage: python3 scripts/vps_like_server.py /app/frontend/build_vps 3100"""
import http.client
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/app/frontend/build_vps"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 3100
BACKEND = ("127.0.0.1", 8001)
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        conn = http.client.HTTPConnection(*BACKEND, timeout=300)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP and k.lower() != "content-length":
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        conn.close()

    def _serve(self):
        if self.path.startswith("/api/"):
            return self._proxy()
        path = self.path.split("?")[0]
        if not os.path.isfile(os.path.join(ROOT, path.lstrip("/"))):
            self.path = "/index.html"
        return super().do_GET()

    do_GET = _serve

    def do_POST(self):
        return self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))


if __name__ == "__main__":
    print(f"VPS-like server on http://127.0.0.1:{PORT} serving {ROOT} (+ /api → {BACKEND[0]}:{BACKEND[1]})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
