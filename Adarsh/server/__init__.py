# © agrprojects
import csv
import json
import os
import time
import yaml
import logging
from collections import defaultdict
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from .stream_routes import router

# ── Log file setup ─────────────────────────────────────────────────────────────
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

# Legacy CSV log
log_file_path = os.path.join(log_dir, "request_logs.csv")
if not os.path.exists(log_file_path):
    with open(log_file_path, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Timestamp", "IP Address", "Endpoint"])

# Structured JSON Lines log (one JSON object per request)
json_log_file_path = os.path.join(log_dir, "request_response_logs.jsonl")

# Initialize FastAPI app
app = FastAPI(docs_url=None, redoc_url=None)

BLOCKED_IPS_FILE = "blocked_ips.yaml"

def load_blocked_ips():
    if not os.path.exists(BLOCKED_IPS_FILE):
        return set()
    with open(BLOCKED_IPS_FILE, "r") as f:
        try:
            data = yaml.safe_load(f)
            return set(data) if data else set()
        except Exception:
            return set()

def save_blocked_ip(ip):
    if not ip or ip == "unknown":
        return
    ips = load_blocked_ips()
    if ip not in ips:
        ips.add(ip)
        with open(BLOCKED_IPS_FILE, "w") as f:
            yaml.dump(list(ips), f)

blocked_ips_cache = load_blocked_ips()
failed_requests = defaultdict(list)

def get_client_ip(request: Request) -> str:
    for header in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
        ip = request.headers.get(header)
        if ip:
            if "," in ip:
                return ip.split(",")[0].strip()
            return ip.strip()
    if request.client:
        return request.client.host
    return "unknown"

def is_malicious_path(path: str) -> bool:
    path_lower = path.lower()
    # Check script extensions
    if any(path_lower.endswith(ext) for ext in (".php", ".php3", ".php4", ".php5", ".phtml", ".asp", ".aspx", ".jsp", ".jspx", ".cgi", ".pl")):
        return True
    # Check WordPress and exploit directory/file keywords
    if any(kw in path_lower for kw in ("wp-admin", "wp-login", "wp-content", "wp-includes", "xmlrpc", "phpunit", "eval-stdin.php", "cgi-bin", "actuator/", "swagger-ui")):
        return True
    # Check sensitive files / hidden folders
    if "/.env" in path_lower or path_lower.startswith(".env") or "/.git" in path_lower or path_lower.startswith(".git"):
        return True
    return False


# ── Pure ASGI Middleware ────────────────────────────────────────────────────────
# NOTE: We deliberately do NOT use @app.middleware("http") / BaseHTTPMiddleware.
# Starlette's BaseHTTPMiddleware is incompatible with streaming responses that
# carry a Content-Length header: it always sends a final empty body chunk after
# the response, which triggers uvicorn's Content-Length validation and causes
# "RuntimeError: Response content shorter than Content-Length" whenever a
# Telegram stream is interrupted. Pure ASGI middleware passes messages through
# unchanged, so a dropped stream just closes the connection cleanly.

class BlockAbuseMiddleware:
    """
    Pure ASGI middleware for IP blocking and abuse rate-limiting.
    Blocks known-malicious paths immediately and tracks repeated 400/404
    failures to auto-ban scanners and abusers.
    """
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        ip_address = get_client_ip(request)
        path = scope.get("path", "")

        # Already-blocked IP — reject immediately
        if ip_address in blocked_ips_cache:
            msg = f"Blocked request from already-blocked IP {ip_address} seeking path {path}"
            logging.warning(msg)
            print(msg, flush=True)
            response = JSONResponse(status_code=403, content={"detail": "IP Blocked due to abuse"})
            await response(scope, receive, send)
            return

        # Malicious path — block and save IP
        if is_malicious_path(path):
            if ip_address != "unknown":
                blocked_ips_cache.add(ip_address)
                save_blocked_ip(ip_address)
                msg = f"IP {ip_address} blocked due to malicious path access: {path}"
            else:
                msg = f"Request blocked due to malicious path access from unknown IP: {path}"
            logging.warning(msg)
            print(msg, flush=True)
            response = JSONResponse(status_code=403, content={"detail": "IP Blocked due to abuse"})
            await response(scope, receive, send)
            return

        # Intercept response status without buffering the body
        status_code_holder: list = [None]

        async def send_interceptor(message):
            if message["type"] == "http.response.start":
                status_code_holder[0] = message["status"]
            try:
                await send(message)
            except RuntimeError as exc:
                # uvicorn raises this when the Telegram stream ends early
                # (timeout) and fewer bytes than Content-Length were sent.
                # Catch it here so it doesn't reach Starlette's error handler,
                # which would try to finalize the response and cause a cascade.
                # The client (download manager) will see a broken connection
                # and retry just this segment automatically.
                if "Content-Length" in str(exc):
                    logging.debug(
                        f"Stream truncated for {ip_address} "
                        f"(Telegram timeout, client will retry): {exc}"
                    )
                    return
                raise

        await self.app(scope, receive, send_interceptor)

        # Post-response: track repeated client errors for auto-banning
        status_code = status_code_holder[0]
        if status_code in (400, 404) and ip_address != "unknown":
            now = datetime.utcnow()
            failed_requests[ip_address].append(now)
            thirty_mins_ago = now.timestamp() - 1800
            failed_requests[ip_address] = [
                t for t in failed_requests[ip_address] if t.timestamp() > thirty_mins_ago
            ]
            if len(failed_requests[ip_address]) > 5:
                blocked_ips_cache.add(ip_address)
                save_blocked_ip(ip_address)
                msg = f"IP {ip_address} blocked due to excessive failed requests (threshold exceeded on {path})"
                logging.warning(msg)
                print(msg, flush=True)


class RequestLoggingMiddleware:
    """
    Pure ASGI middleware that logs every HTTP request + response to:
      - logs/request_logs.csv         (legacy, one line per request)
      - logs/request_response_logs.jsonl  (full detail JSON Lines)

    Each JSONL entry has the shape:
      {
        "timestamp": "...",
        "duration_ms": 123.4,
        "request": { method, url, path, query_params, headers, client_ip },
        "response": { status_code, headers }
      }

    Query the file with jq, e.g.:
      cat logs/request_response_logs.jsonl | jq 'select(.response.status_code == 206)'
      cat logs/request_response_logs.jsonl | jq 'select(.request.headers["range"] != null)'
    """
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        t_start = time.monotonic()
        ts = datetime.utcnow().isoformat() + "Z"
        ip_address = get_client_ip(request)

        # ── Collect request details ──────────────────────────────────────────
        req_headers = dict(request.headers)   # includes Range, User-Agent, etc.
        req_info = {
            "method":       request.method,
            "url":          str(request.url),
            "path":         request.url.path,
            "query_params": dict(request.query_params),
            "headers":      req_headers,
            "client_ip":    ip_address,
        }

        # ── Intercept response to capture status + headers ───────────────────
        resp_status  = None
        resp_headers = {}

        async def send_logger(message):
            nonlocal resp_status, resp_headers
            if message["type"] == "http.response.start":
                resp_status  = message["status"]
                resp_headers = {
                    k.decode("latin-1"): v.decode("latin-1")
                    for k, v in message.get("headers", [])
                }
            await send(message)

        await self.app(scope, receive, send_logger)

        duration_ms = round((time.monotonic() - t_start) * 1000, 2)

        # ── Build JSON entry ─────────────────────────────────────────────────
        entry = {
            "timestamp":   ts,
            "duration_ms": duration_ms,
            "request":  req_info,
            "response": {
                "status_code": resp_status,
                "headers":     resp_headers,
                # Body is not logged for streaming responses.
                # Use content-length / content-range from headers above.
                "body_note": (
                    "streaming — see content-range / content-length in headers"
                    if resp_headers.get("content-range") else "see headers"
                ),
            },
        }

        # ── Write to JSONL (append, one object per line) ─────────────────────
        try:
            with open(json_log_file_path, "a") as jf:
                jf.write(json.dumps(entry) + "\n")
        except Exception as e:
            logging.warning(f"Failed to write JSON log: {e}")

        # ── Legacy CSV log ───────────────────────────────────────────────────
        try:
            with open(log_file_path, mode='a', newline='') as file:
                csv.writer(file).writerow([ts, ip_address, str(request.url)])
        except Exception as e:
            logging.warning(f"Failed to write CSV log: {e}")


# Register pure ASGI middleware (order: last added = outermost).
# BlockAbuseMiddleware is outermost so it runs first on every request.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(BlockAbuseMiddleware)

# Define the route to serve the favicon.ico
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("Adarsh/favicon.ico")

# Include routes from stream_routes
app.include_router(router)
