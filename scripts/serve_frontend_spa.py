#!/usr/bin/env python3
"""Serve the frontend with SPA history fallback for local development."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class SPARequestHandler(SimpleHTTPRequestHandler):
    """Return index.html for extensionless routes such as /login and /chat."""

    def send_head(self):
        requested = Path(self.translate_path(self.path.split("?", 1)[0]))
        if not requested.exists() and "." not in Path(self.path.split("?", 1)[0]).name:
            self.path = "/index.html"
        return super().send_head()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve frontend files with SPA fallback.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--directory", default=str(Path(__file__).resolve().parents[1] / "frontend"))
    args = parser.parse_args()

    handler = lambda *handler_args, **handler_kwargs: SPARequestHandler(
        *handler_args,
        directory=args.directory,
        **handler_kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving frontend from {args.directory} on http://{args.host}:{args.port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
