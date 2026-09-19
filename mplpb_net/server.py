"""
Serving a node -- static files over HTTP, standard library only.

`python3 -m mplpb_net serve <node>` is a convenience, not a requirement. Any
static web server pointed at the node directory works, provided it serves
only what a stranger should see:

    node.json, node.html, corpora/**      served
    local/, known/, cache/, config.json   never served

There is no API. A reader GETs files and verifies them itself.
"""

from __future__ import annotations

import functools
import posixpath
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

PUBLIC_FILES = {"node.json", "node.html"}
PUBLIC_DIRS = ("corpora/",)


def is_public(url_path: str) -> bool:
    rel = posixpath.normpath(unquote(urlparse(url_path).path)).lstrip("/")
    if rel.startswith(".."):
        return False
    return rel in PUBLIC_FILES or rel.startswith(PUBLIC_DIRS) or rel in ("", ".")


class NodeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        if not is_public(self.path):
            self.send_error(404, "not served")
            return None
        rel = posixpath.normpath(unquote(urlparse(self.path).path)).lstrip("/")
        if rel in ("", "."):
            self.send_response(302)
            self.send_header("Location", "/node.html")
            self.end_headers()
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404, "no directory listings")
        return None

    def log_message(self, fmt, *args):  # quiet by default
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)


def make_server(node_root: Path, host: str = "127.0.0.1", port: int = 0, verbose: bool = False):
    handler = functools.partial(NodeHandler, directory=str(Path(node_root).resolve()))
    server = ThreadingHTTPServer((host, port), handler)
    server.verbose = verbose
    return server


def serve_in_thread(node_root: Path, host: str = "127.0.0.1", port: int = 0):
    server = make_server(node_root, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_address[1]}/"
