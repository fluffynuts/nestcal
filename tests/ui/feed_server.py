import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FeedServer:
    """Serves one fake .ics feed from this process, so the app under test makes
    real HTTP requests. Change .body / .status between polls to change the feed."""

    def __init__(self):
        self.body = b""
        self.status = 200
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests += 1
                self.send_response(outer.status)
                self.send_header("Content-Type", "text/calendar")
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/calendar.ics"
        self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.01), daemon=True)

    def start(self) -> "FeedServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
