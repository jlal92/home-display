"""Throwaway probe server for the iPad. Python standard library only.

Usage (from this folder):  python server.py [port]
- Serves the probe pages over plain HTTP (no TLS; HTTPS is a separate question).
- /ping.json  -> {"server_time": "<ISO UTC>"}   (same-origin XHR test)
- /report?m=..&p=..  -> prints iPad-side errors and appends to errors.log
- Every request is logged with the client's User-Agent, so a hit from the
  iPad proves the network path works.
Binds 0.0.0.0 so the iPad can reach it. Stop it with Ctrl+C when done.
"""
import datetime
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/ping.json":
            body = json.dumps(
                {"server_time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/report":
            q = parse_qs(u.query)
            line = "%s %s %s" % (
                datetime.datetime.now().isoformat(timespec="seconds"),
                q.get("p", ["?"])[0],
                q.get("m", ["?"])[0][:500],
            )
            print("IPAD ERROR:", line)
            with open(os.path.join(HERE, "errors.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        print("%s %s | %s" % (self.client_address[0], fmt % args, self.headers.get("User-Agent", "")[:90]))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print("Probe server on 0.0.0.0:%d  (Ctrl+C to stop)" % port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
