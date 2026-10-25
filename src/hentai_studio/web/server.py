from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .application import RequestError, Response, StudioApplication


def make_server(app: StudioApplication, host: str = "127.0.0.1", port: int = 7860) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "HENTAIStudio/0.2"
        timeout = 15

        def log_message(self, format: str, *args: object) -> None:
            pass

        def _send(self, response: Response) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(response.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self) -> None:
            self._send(app.dispatch("GET", self.path))

        def do_POST(self) -> None:
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise RequestError("chunked requests are not supported")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as error:
                    raise RequestError("invalid Content-Length") from error
                if length < 0:
                    raise RequestError("invalid Content-Length")
                if length > 131_072:
                    raise RequestError("request too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise RequestError("incomplete request body")
                response = app.dispatch("POST", self.path, body)
            except RequestError as error:
                response = Response.json({"error": str(error)}, error.status)
            except (TimeoutError, OSError):
                response = Response.json({"error": "request body timed out"}, HTTPStatus.REQUEST_TIMEOUT)
            self._send(response)

    return ThreadingHTTPServer((host, port), Handler)


def serve(app: StudioApplication, host: str, port: int) -> None:
    with make_server(app, host, port) as server:
        print(f"HENTAI Studio: http://{host}:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
