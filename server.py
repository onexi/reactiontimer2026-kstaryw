import json
import random
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


HOST = "127.0.0.1"
PORT = 8000

MIN_DELAY_MS = 2000
MAX_DELAY_MS = 5000
MIN_HUMAN_MS = 80

RATE_LIMIT_WINDOW_MS = 2000
RATE_LIMIT_MAX_CLICKS = 5


sessions = {}
best_time_ms = None


def now_ms():
    return int(time.time() * 1000)


def json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler, status, body, content_type="text/html; charset=utf-8"):
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            try:
                with open("index.html", "r", encoding="utf-8") as f:
                    text_response(self, 200, f.read())
            except FileNotFoundError:
                text_response(self, 404, "Missing index.html", "text/plain; charset=utf-8")
            return
        if parsed.path == "/best":
            payload = {"best_time_ms": best_time_ms}
            return json_response(self, 200, payload)
        text_response(self, 404, "Not Found", "text/plain; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""

        if parsed.path == "/start":
            return self.handle_start()
        if parsed.path == "/click":
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                return json_response(self, 400, {"error": "bad_json"})
            return self.handle_click(data)
        return json_response(self, 404, {"error": "not_found"})

    def handle_start(self):
        session_id = secrets.token_urlsafe(12)
        delay_ms = random.randint(MIN_DELAY_MS, MAX_DELAY_MS)
        go_at = now_ms() + delay_ms

        sessions[session_id] = {
            "go_at": go_at,
            "used": False,
            "window_start": 0,
            "window_clicks": 0,
        }

        payload = {
            "session_id": session_id,
            "delay_ms": delay_ms,
        }
        return json_response(self, 200, payload)

    def handle_click(self, data):
        global best_time_ms
        session_id = data.get("session_id")
        if not session_id or session_id not in sessions:
            return json_response(self, 400, {"error": "invalid_session"})

        session = sessions[session_id]
        if session["used"]:
            return json_response(self, 409, {"error": "session_used"})

        now = now_ms()

        window_start = session["window_start"]
        if now - window_start > RATE_LIMIT_WINDOW_MS:
            session["window_start"] = now
            session["window_clicks"] = 0

        session["window_clicks"] += 1
        if session["window_clicks"] > RATE_LIMIT_MAX_CLICKS:
            session["used"] = True
            return json_response(self, 429, {"error": "rate_limited"})

        go_at = session["go_at"]

        if now < go_at:
            session["used"] = True
            return json_response(self, 200, {
                "result": "failed",
                "reason": "before_go",
                "too_fast": False,
                "reaction_ms": None,
                "best_time_ms": best_time_ms,
            })

        reaction_ms = now - go_at
        too_fast = reaction_ms < MIN_HUMAN_MS

        if best_time_ms is None or reaction_ms < best_time_ms:
            best_time_ms = reaction_ms

        session["used"] = True
        return json_response(self, 200, {
            "result": "ok",
            "too_fast": too_fast,
            "reaction_ms": reaction_ms,
            "best_time_ms": best_time_ms,
        })

    def log_message(self, fmt, *args):
        return


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Serving on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
