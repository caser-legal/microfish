#!/usr/bin/env python3
"""
MicroFish UI static server.

Serves the pre-built Vue frontend (frontend/dist) with single-page-app
fallback so vue-router deep links resolve to index.html. Used by the
packaged macOS app so no Node.js runtime is required.

Usage:
    python serve_dist.py --dir ./frontend/dist --port 3000 --host 127.0.0.1
"""

import argparse
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class SPAHandler(SimpleHTTPRequestHandler):
    """Static handler that falls back to index.html for client-side routes."""

    def do_GET(self):  # noqa: N802 - stdlib API
        requested = self.path.split("?", 1)[0].split("#", 1)[0]
        fs_path = self.translate_path(requested)
        is_file = os.path.isfile(fs_path)
        # A route with no file extension and no matching file is treated as
        # a client-side route and served by index.html.
        has_extension = "." in os.path.basename(requested.rstrip("/"))
        if not is_file and not has_extension:
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *args):  # silence default request logging
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="MicroFish UI static server")
    parser.add_argument("--dir", required=True, help="directory to serve")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    handler = partial(SPAHandler, directory=args.dir)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        f"MicroFish UI serving {args.dir} at http://{args.host}:{args.port}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
