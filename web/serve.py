"""Tiny dev server for the dashboard.

Avoids file:// CORS issues that block fetch("data.json") in some browsers.
Just runs Python's stdlib http.server in this folder and opens the page.

Usage:
    python web/serve.py
"""

from __future__ import annotations

import http.server
import os
import socketserver
import sys
import webbrowser
from pathlib import Path


PORT = 8765


def main() -> None:
    here = Path(__file__).resolve().parent
    os.chdir(here)
    handler = http.server.SimpleHTTPRequestHandler
    handler.extensions_map.update({".json": "application/json"})

    with socketserver.TCPServer(("127.0.0.1", PORT), handler) as httpd:
        url = f"http://127.0.0.1:{PORT}/index.html"
        print(f"Dashboard at  {url}")
        print(f"Serving from  {here}")
        print("Press Ctrl+C to stop")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down")
            httpd.shutdown()


if __name__ == "__main__":
    sys.exit(main())
