import email.utils
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit


UPSTREAM_URL = os.getenv("UPSTREAM_URL", "https://api.openai.com")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
UPSTREAM_AUTH_HEADER = os.getenv("UPSTREAM_AUTH_HEADER", "Authorization")
UPSTREAM_AUTH_SCHEME = os.getenv("UPSTREAM_AUTH_SCHEME", "Bearer")
try:
    MODEL_MAP = json.loads(os.getenv("MODEL_MAP", "{}"))
except json.JSONDecodeError as error:
    raise SystemExit("MODEL_MAP must be a JSON object") from error
if not isinstance(MODEL_MAP, dict) or not all(
    isinstance(key, str) and isinstance(value, str)
    for key, value in MODEL_MAP.items()
):
    raise SystemExit("MODEL_MAP must be a JSON object with string keys and values")
try:
    ROUTE_MAP = json.loads(os.getenv("ROUTE_MAP", "{}"))
except json.JSONDecodeError as error:
    raise SystemExit("ROUTE_MAP must be a JSON object") from error
if not isinstance(ROUTE_MAP, dict) or not all(
    isinstance(key, str) and key.startswith("/")
    and isinstance(value, str) and value.startswith("/")
    for key, value in ROUTE_MAP.items()
):
    raise SystemExit("ROUTE_MAP must map absolute path prefixes to absolute path prefixes")
if not UPSTREAM_API_KEY:
    raise SystemExit("UPSTREAM_API_KEY must be set before starting the proxy")

MAX_TPM = int(os.getenv("MAX_TPM", "240000"))
MAX_RPM = int(os.getenv("MAX_RPM", "240"))
WINDOW_SECONDS = 60.0
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("PROXY_TIMEOUT", "300"))
MAX_RETRIES = int(os.getenv("PROXY_MAX_RETRIES", "5"))
MAX_RETRY_AFTER_SECONDS = float(os.getenv("PROXY_MAX_RETRY_AFTER", "60"))

if MAX_TPM <= 0 or MAX_RPM <= 0:
    raise SystemExit("MAX_TPM and MAX_RPM must be positive integers")

# Entries cover both queued/sent reservations and finalized actual token usage.
# A reservation remains in the rolling window for a full minute, avoiding a
# reset-boundary burst and ensuring in-flight requests count against the limit.
_rate_limit_lock = threading.Lock()
_rate_limit_entries = deque()
_telemetry_lock = threading.Lock()
_rate_limit_state = {
    "requests_remaining": None,
    "tokens_remaining": None,
    "requests_reset": None,
    "tokens_reset": None,
    "retry_after": None,
    "updated_at": None,
}
_cooldown_until = 0.0


def estimate_tokens(body):
    """Return a conservative request-token estimate from the JSON payload."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return max(1, (len(body) + 3) // 4)

    prompt_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(prompt_text.encode("utf-8")) + 3) // 4)


def _prune_rate_limit_entries(now):
    cutoff = now - WINDOW_SECONDS
    while _rate_limit_entries and _rate_limit_entries[0]["time"] <= cutoff:
        _rate_limit_entries.popleft()


def reserve_capacity(estimated_tokens):
    """Wait until rolling-window capacity is available, then reserve it."""
    reservation = {"tokens": estimated_tokens, "time": time.monotonic()}
    while True:
        now = time.monotonic()
        with _rate_limit_lock:
            now = time.monotonic()
            _prune_rate_limit_entries(now)
            token_total = sum(entry["tokens"] for entry in _rate_limit_entries)
            request_total = len(_rate_limit_entries)

            if token_total + estimated_tokens <= MAX_TPM and request_total + 1 <= MAX_RPM:
                reservation["time"] = now
                _rate_limit_entries.append(reservation)
                return reservation

            wait_seconds = max(
                0.05,
                _rate_limit_entries[0]["time"] + WINDOW_SECONDS - now,
            )

        print(f"[Proxy] Rate limit reached. Holding request for {wait_seconds:.2f}s...")
        time.sleep(min(wait_seconds, 0.5))


def release_reservation(reservation):
    """Remove an unsuccessful request's reservation immediately."""
    with _rate_limit_lock:
        try:
            _rate_limit_entries.remove(reservation)
        except ValueError:
            pass


def reconcile_reservation(reservation, actual_tokens):
    """Adjust a reservation using upstream-reported usage when available."""
    if actual_tokens is None or actual_tokens <= 0:
        return
    with _rate_limit_lock:
        if reservation in _rate_limit_entries:
            reservation["tokens"] = actual_tokens


def _get_header(headers, name):
    value = headers.get(name)
    if value is not None:
        return value
    name = name.lower()
    return next((value for key, value in headers.items() if key.lower() == name), None)


def update_rate_limit_state(headers, status):
    """Capture provider rate-limit headers and install a shared 429 cooldown."""
    global _cooldown_until
    names = {
        "requests_remaining": (
            "anthropic-ratelimit-requests-remaining",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining",
        ),
        "tokens_remaining": (
            "anthropic-ratelimit-tokens-remaining",
            "x-ratelimit-remaining-tokens",
        ),
        "requests_reset": (
            "anthropic-ratelimit-requests-reset",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset",
        ),
        "tokens_reset": (
            "anthropic-ratelimit-tokens-reset",
            "x-ratelimit-reset-tokens",
        ),
    }
    updates = {}
    for field, header_names in names.items():
        value = next(
            (found for name in header_names if (found := _get_header(headers, name)) is not None),
            None,
        )
        if value is not None:
            updates[field] = value

    retry_after = parse_retry_after(_get_header(headers, "Retry-After"))
    with _telemetry_lock:
        _rate_limit_state.update(updates)
        if retry_after is not None:
            _rate_limit_state["retry_after"] = retry_after
        _rate_limit_state["updated_at"] = time.time()
        if status == 429 and retry_after is not None:
            _cooldown_until = max(
                _cooldown_until,
                time.monotonic() + min(retry_after, MAX_RETRY_AFTER_SECONDS),
            )


def rate_limit_snapshot():
    with _telemetry_lock:
        state = dict(_rate_limit_state)
        state["cooldown_seconds"] = max(0.0, _cooldown_until - time.monotonic())
        return state


def wait_for_upstream_cooldown():
    while True:
        with _telemetry_lock:
            wait_seconds = _cooldown_until - time.monotonic()
        if wait_seconds <= 0:
            return
        print(f"[Proxy] Upstream cooldown active. Holding request for {wait_seconds:.2f}s...")
        time.sleep(min(wait_seconds, 0.5))


def parse_retry_after(value, now=None):
    """Parse Retry-After delta-seconds or HTTP-date; return None if invalid."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            current_time = time.time() if now is None else now
            return max(0.0, retry_at.timestamp() - current_time)
        except (TypeError, ValueError, OverflowError):
            return None


def make_upstream_request(body, target=None, method="POST", client_headers=None):
    target = target or "/v1/chat/completions"
    upstream = urlsplit(UPSTREAM_URL)
    configured_path = upstream.path.rstrip("/")
    if configured_path.endswith("/v1/chat/completions"):
        configured_path = configured_path[: -len("/v1/chat/completions")]
    if not configured_path:
        configured_path = ""
    incoming = urlsplit(target)
    if incoming.scheme or incoming.netloc or not incoming.path.startswith("/"):
        raise ValueError("Request target must be an absolute path")
    incoming_path = incoming.path
    if incoming_path in ("", "/"):
        incoming_path = "/v1/chat/completions"
    for source, destination in sorted(ROUTE_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if incoming_path == source or incoming_path.startswith(source.rstrip("/") + "/"):
            incoming_path = destination.rstrip("/") + incoming_path[len(source.rstrip("/")):]
            break
    if configured_path and (incoming_path == configured_path or incoming_path.startswith(configured_path + "/")):
        upstream_path = incoming_path
    else:
        upstream_path = f"{configured_path}/{incoming_path.lstrip('/')}"
    url = urlunsplit(
        (
            upstream.scheme,
            upstream.netloc,
            upstream_path,
            incoming.query or upstream.query,
            "",
        )
    )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("model"), str):
        mapped_model = MODEL_MAP.get(payload["model"])
        if mapped_model is not None:
            payload["model"] = mapped_model
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    auth_value = " ".join(
        part for part in (UPSTREAM_AUTH_SCHEME, UPSTREAM_API_KEY) if part
    )
    headers = {
        "Content-Type": "application/json",
        UPSTREAM_AUTH_HEADER: auth_value,
    }
    hop_by_hop = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
        "authorization", "api-key", "x-api-key", "cookie", "x-session-id", "x-cline-session",
        UPSTREAM_AUTH_HEADER.lower(),
    }
    if client_headers:
        connection_tokens = {
            token.strip().lower()
            for token in (_get_header(client_headers, "Connection") or "").split(",")
            if token.strip()
        }
        for name, value in client_headers.items():
            if name.lower() not in hop_by_hop | connection_tokens:
                headers[name] = value
    return urllib.request.Request(
        url,
        data=body if method not in {"GET", "HEAD"} else None,
        headers=headers,
        method=method,
    )


def forward_request(body, target=None, method="POST", headers=None):
    """Forward once or retry transient upstream 429 responses with bounded delay."""
    backoff = 1.0
    wait_for_upstream_cooldown()
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(
                make_upstream_request(body, target, method, headers), timeout=UPSTREAM_TIMEOUT_SECONDS
            ) as response:
                update_rate_limit_state(response.headers, response.status)
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            update_rate_limit_state(error.headers, error.code)
            response_body = error.read()
            if error.code != 429 or attempt + 1 >= MAX_RETRIES:
                return error.code, error.headers, response_body

            retry_after = parse_retry_after(_get_header(error.headers, "Retry-After"))
            delay = retry_after if retry_after is not None else backoff
            delay = min(delay, MAX_RETRY_AFTER_SECONDS)
            print(
                f"[Proxy] Upstream returned 429. Retry {attempt + 1}/{MAX_RETRIES} "
                f"in {delay:.2f}s..."
            )
            time.sleep(delay)
            backoff = min(backoff * 2, MAX_RETRY_AFTER_SECONDS)
        except Exception as error:
            response_body = json.dumps({"error": str(error)}).encode("utf-8")
            return 502, {}, response_body

    return 502, {}, b'{"error":"Upstream request retries exhausted"}'


class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/rate-limits":
            body = json.dumps(rate_limit_snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._forward_client_request()

    def do_POST(self):
        self._forward_client_request()

    def do_PUT(self):
        self._forward_client_request()

    def do_PATCH(self):
        self._forward_client_request()

    def do_DELETE(self):
        self._forward_client_request()

    def do_HEAD(self):
        self._forward_client_request()

    def do_OPTIONS(self):
        self._forward_client_request()

    def do_TRACE(self):
        self.send_error(405)

    def _forward_client_request(self):
        target = urlsplit(self.path)
        if target.scheme or target.netloc or not target.path.startswith("/"):
            self.send_error(400, "Request target must be an absolute path")
            return
        if target.path in ("/health", "/rate-limits"):
            self.send_error(404)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            self.send_error(400, "Incomplete request body")
            return

        if body:
            try:
                json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400, "Request body must be valid JSON")
                return
        if body and self.command not in {"POST", "PUT", "PATCH"}:
            self.send_error(400, "JSON request body is not supported for this method")
            return

        estimated_tokens = estimate_tokens(body)
        if estimated_tokens > MAX_TPM:
            self.send_error(413, "Request exceeds configured MAX_TPM")
            return

        reservation = reserve_capacity(estimated_tokens)
        try:
            status, headers, response_body = forward_request(
                body,
                self.path,
                self.command,
                self.headers,
            )
            if not 200 <= status < 300:
                release_reservation(reservation)
            else:
                try:
                    response_data = json.loads(response_body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    response_data = None

                usage = response_data.get("usage", {}) if isinstance(response_data, dict) else {}
                actual_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
                if isinstance(actual_tokens, (int, float)) and actual_tokens > 0:
                    reconcile_reservation(reservation, actual_tokens)
                else:
                    release_reservation(reservation)
        except Exception:
            release_reservation(reservation)
            raise

        self.send_response(status)
        content_type = headers.get("Content-Type", "application/json")
        self.send_header("Content-Type", content_type)
        for name in (
            "Retry-After",
            "anthropic-ratelimit-requests-remaining",
            "anthropic-ratelimit-requests-reset",
            "anthropic-ratelimit-tokens-remaining",
            "anthropic-ratelimit-tokens-reset",
            "x-ratelimit-remaining",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            value = _get_header(headers, name)
            if value is not None:
                self.send_header(name, value)
        if self.command != "HEAD":
            self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_body)

    def log_message(self, format, *args):
        return


def run():
    server_address = (
        os.getenv("PROXY_HOST", "0.0.0.0"), int(os.getenv("PROXY_PORT", "4000"))
    )
    httpd = ThreadingHTTPServer(server_address, ProxyHandler)
    httpd.daemon_threads = True
    print(
        "Threaded rate-limiting proxy running on http://{}:{}".format(*server_address)
    )
    httpd.serve_forever()


if __name__ == "__main__":
    run()