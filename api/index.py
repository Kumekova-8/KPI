"""WSGI entry point for the online KPI demonstration."""

import os
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from tempfile import gettempdir
from threading import Lock
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlencode
from wsgiref.headers import Headers

from kpi.db import DB, encode
from kpi.seed import seed
from kpi.server import Handler

_initialize_lock = Lock()


@lru_cache(maxsize=1)
def database():
    location = os.environ.get("KPI_DATABASE") or Path(gettempdir()) / "kpi-vercel-demo.sqlite3"
    db = DB(location)
    db.migrate()
    seed(db)
    return db


class Request(Handler):
    def __init__(self, environ, path, db):
        self.path = path
        self.server = SimpleNamespace(db=db)
        self.client_address = (environ.get("REMOTE_ADDR", ""), 0)
        self.rfile = environ["wsgi.input"]
        self.https = environ.get("wsgi.url_scheme") == "https" or bool(os.getenv("VERCEL"))
        self.headers = Headers([
            (key[5:].replace("_", "-"), value)
            for key, value in environ.items() if key.startswith("HTTP_")
        ])
        for key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            if environ.get(key):
                self.headers[key.replace("_", "-")] = environ[key]

    def respond(self, status, data, media="application/json; charset=utf-8", headers=None):
        self.status = status
        self.data = data if isinstance(data, bytes) else encode(data).encode("utf-8")
        self.response_headers = [
            ("Content-Type", media),
            ("Content-Length", str(len(self.data))),
            ("Cache-Control", "no-store"),
        ]
        for key, value in (headers or {}).items():
            if key.lower() == "set-cookie" and self.https and "; secure" not in value.lower():
                value += "; Secure"
            self.response_headers.append((key, value))


def app(environ, start_response):
    pairs = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    query = urlencode([(key, value) for key, value in pairs if key != "__kpi_endpoint"])
    path = environ.get("PATH_INFO", "/")
    if path in {"/api/index", "/api/index.py", "/"}:
        endpoints = [value for key, value in pairs if key == "__kpi_endpoint"]
        if endpoints:
            path = "/api/" + endpoints[0].lstrip("/")

    method = environ.get("REQUEST_METHOD", "GET")
    with _initialize_lock:
        db = database()
    request = Request(environ, path + ("?" + query if query else ""), db)
    if method in {"GET", "POST", "PUT", "DELETE"} and path.startswith("/api/"):
        request.handle_request(method)
    else:
        request.respond(404, {"error": "Маршрут не найден."})
    start_response(f"{request.status} {HTTPStatus(request.status).phrase}", request.response_headers)
    return [request.data]
