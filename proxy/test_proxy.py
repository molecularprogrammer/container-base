import email.utils
import importlib.util
import io
import json
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


PROXY_PATH = Path(__file__).resolve().parent / "main.py"
spec = importlib.util.spec_from_file_location("proxy", PROXY_PATH)
proxy = importlib.util.module_from_spec(spec)
with mock.patch.dict(os.environ, {"UPSTREAM_API_KEY": "test-key"}):
    spec.loader.exec_module(proxy)


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"{}"):
        self.status = status
        self.headers = headers or {}
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class RepeatableHTTPError(proxy.urllib.error.HTTPError):
    def __init__(self, code, body, headers=None):
        super().__init__("https://upstream.invalid", code, "upstream error", headers or {}, None)
        self.response_body = body

    def read(self):
        return self.response_body


class ProxyTests(unittest.TestCase):
    def setUp(self):
        with proxy._rate_limit_lock:
            proxy._rate_limit_entries.clear()
        with proxy._telemetry_lock:
            proxy._rate_limit_state.update({
                "requests_remaining": None,
                "tokens_remaining": None,
                "requests_reset": None,
                "tokens_reset": None,
                "retry_after": None,
                "updated_at": None,
            })
            proxy._cooldown_until = 0.0

    def test_estimate_tokens_handles_json_and_invalid_utf8(self):
        self.assertEqual(proxy.estimate_tokens(b'{"prompt":"abc"}'), 4)
        self.assertEqual(proxy.estimate_tokens(b"\xff"), 1)

    def test_reservation_waits_for_rpm_window_without_serializing_callers(self):
        old_rpm = proxy.MAX_RPM
        old_tpm = proxy.MAX_TPM
        old_window = proxy.WINDOW_SECONDS
        proxy.MAX_RPM = 1
        proxy.MAX_TPM = 100
        proxy.WINDOW_SECONDS = 0.12
        reservations = []
        errors = []
        release_first = threading.Event()

        def reserve():
            try:
                reservation = proxy.reserve_capacity(1)
                reservations.append((time.monotonic(), reservation))
                if reservation is first_reservation:
                    release_first.wait(timeout=2)
            except Exception as error:  # propagate worker failures to the test
                errors.append(error)

        first_reservation = proxy.reserve_capacity(1)
        first_time = time.monotonic()
        threads = [threading.Thread(target=reserve) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            # A call on the main thread must get its own slot only after expiry.
            third_reservation = proxy.reserve_capacity(1)
            third_time = time.monotonic()
            for thread in threads:
                thread.join(timeout=2)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(reservations), 2)
            self.assertGreaterEqual(third_time - first_time, 0.10)
            self.assertIsNotNone(third_reservation)
        finally:
            release_first.set()
            proxy.MAX_RPM = old_rpm
            proxy.MAX_TPM = old_tpm
            proxy.WINDOW_SECONDS = old_window

    def test_reconcile_updates_reservation_under_limit_lock(self):
        reservation = {"tokens": 10, "time": time.monotonic()}
        proxy._rate_limit_entries.append(reservation)
        proxy.reconcile_reservation(reservation, 17)
        self.assertEqual(reservation["tokens"], 17)
        proxy.reconcile_reservation(reservation, None)
        self.assertEqual(reservation["tokens"], 17)

    def test_prune_removes_expired_dict_entries(self):
        old_window = proxy.WINDOW_SECONDS
        proxy.WINDOW_SECONDS = 10
        expired = {"tokens": 5, "time": 1}
        current = {"tokens": 7, "time": 5}
        try:
            proxy._rate_limit_entries.extend((expired, current))

            proxy._prune_rate_limit_entries(12)

            self.assertEqual(list(proxy._rate_limit_entries), [current])
        finally:
            proxy.WINDOW_SECONDS = old_window

    def test_reserve_capacity_keeps_waiting_until_capacity_is_available(self):
        old_rpm = proxy.MAX_RPM
        old_window = proxy.WINDOW_SECONDS
        proxy.MAX_RPM = 1
        proxy.WINDOW_SECONDS = 0.08
        first_reservation = proxy.reserve_capacity(1)
        result = {}
        thread = threading.Thread(
            target=lambda: result.setdefault("reservation", proxy.reserve_capacity(1))
        )
        try:
            thread.start()
            thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertIn("reservation", result)
            self.assertGreaterEqual(
                result["reservation"]["time"] - first_reservation["time"], 0.07
            )
        finally:
            proxy.MAX_RPM = old_rpm
            proxy.WINDOW_SECONDS = old_window

    def test_release_reservation_removes_entry_immediately(self):
        reservation = proxy.reserve_capacity(1)

        proxy.release_reservation(reservation)

        self.assertNotIn(reservation, proxy._rate_limit_entries)

    def test_parse_retry_after_delta_and_http_date(self):
        self.assertEqual(proxy.parse_retry_after("2.5"), 2.5)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        retry_at = now + timedelta(seconds=12)
        value = email.utils.format_datetime(retry_at, usegmt=True)
        self.assertEqual(proxy.parse_retry_after(value, now=now.timestamp()), 12)
        self.assertIsNone(proxy.parse_retry_after("not a date"))
        self.assertIsNone(proxy.parse_retry_after(None))

    def test_make_upstream_request_uses_configured_url_and_auth_header(self):
        with mock.patch.multiple(
            proxy,
            UPSTREAM_URL="https://provider.invalid",
            UPSTREAM_API_KEY="test-key",
            UPSTREAM_AUTH_HEADER="x-api-key",
            UPSTREAM_AUTH_SCHEME="",
            MODEL_MAP={},
        ):
            request = proxy.make_upstream_request(
                b"{}",
                "/v1/messages?beta=true",
                "GET",
                {
                    "X-Trace-ID": "trace-1",
                    "Host": "session.invalid",
                    "X-API-Key": "fake",
                },
            )

        self.assertEqual(request.full_url, "https://provider.invalid/v1/messages?beta=true")
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        self.assertEqual(request.get_header("X-trace-id"), "trace-1")
        self.assertIsNone(request.get_header("Host"))
        self.assertIsNone(request.get_header("X-session-id"))
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)

    def test_make_upstream_request_maps_model_alias(self):
        with mock.patch.multiple(
            proxy,
            UPSTREAM_URL="https://provider.invalid/api",
            UPSTREAM_API_KEY="test-key",
            MODEL_MAP={"fast": "provider/model-v2"},
        ):
            request = proxy.make_upstream_request(
                b'{"model":"fast","messages":[]}', "/v1/chat/completions"
            )

        self.assertEqual(request.full_url, "https://provider.invalid/api/v1/chat/completions")
        self.assertEqual(
            json.loads(request.data),
            {"model": "provider/model-v2", "messages": []},
        )

    def test_make_upstream_request_maps_longest_configured_route_prefix(self):
        with mock.patch.multiple(
            proxy,
            UPSTREAM_URL="https://provider.invalid",
            UPSTREAM_API_KEY="test-key",
            ROUTE_MAP={"/v1": "/api/v2", "/v1/messages": "/messages"},
        ):
            request = proxy.make_upstream_request(b"{}", "/v1/messages/count_tokens")

        self.assertEqual(request.full_url, "https://provider.invalid/messages/count_tokens")

    def test_rate_limit_state_tracks_provider_headers_and_429_cooldown(self):
        with mock.patch.object(proxy.time, "monotonic", return_value=100.0):
            proxy.update_rate_limit_state(
                {
                    "Anthropic-Ratelimit-Requests-Remaining": "8",
                    "x-ratelimit-remaining-tokens": "1200",
                    "Retry-After": "4",
                },
                429,
            )
            state = proxy.rate_limit_snapshot()
        self.assertEqual(state["requests_remaining"], "8")
        self.assertEqual(state["tokens_remaining"], "1200")
        self.assertEqual(state["retry_after"], 4.0)
        self.assertEqual(state["cooldown_seconds"], 4.0)

    def test_rate_limit_endpoint_returns_telemetry_json(self):
        proxy.update_rate_limit_state({"x-ratelimit-remaining": "11"}, 200)
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            connection.request("GET", "/rate-limits")
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(body["requests_remaining"], "11")
            self.assertIn("cooldown_seconds", body)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_forward_retries_429_then_returns_success(self):
        error = proxy.urllib.error.HTTPError(
            "https://upstream.invalid", 429, "rate limited", {"Retry-After": "3"}, io.BytesIO(b"busy")
        )
        response = FakeResponse(
            headers={"Content-Type": "application/json"},
            body=b'{"usage":{"total_tokens":4}}',
        )
        with mock.patch.object(proxy.urllib.request, "urlopen", side_effect=[error, response]) as urlopen:
            with mock.patch.object(proxy.time, "sleep") as sleep:
                status, headers, body = proxy.forward_request(b"{}")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body, b'{"usage":{"total_tokens":4}}')
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(3.0)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], proxy.UPSTREAM_TIMEOUT_SECONDS)

    def test_forward_returns_last_429_after_retry_limit(self):
        proxy_max_retries = proxy.MAX_RETRIES
        proxy.MAX_RETRIES = 2
        error = RepeatableHTTPError(429, b"still busy")
        try:
            with mock.patch.object(proxy.urllib.request, "urlopen", side_effect=error) as urlopen:
                with mock.patch.object(proxy.time, "sleep"):
                    status, _headers, body = proxy.forward_request(b"{}")
            self.assertEqual(status, 429)
            self.assertEqual(body, b"still busy")
            self.assertEqual(urlopen.call_count, 2)
        finally:
            proxy.MAX_RETRIES = proxy_max_retries

    def test_forward_maps_transport_error_to_502(self):
        with mock.patch.object(proxy.urllib.request, "urlopen", side_effect=OSError("offline")):
            status, _headers, body = proxy.forward_request(b"{}")
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body), {"error": "offline"})

    def test_health_endpoint_works_while_post_is_waiting(self):
        entered_forward = threading.Event()
        release_forward = threading.Event()

        def hold_forward(_body, _target=None, _method="POST", _headers=None):
            entered_forward.set()
            if not release_forward.wait(timeout=2):
                raise TimeoutError("test did not release mocked upstream")
            return 200, {"Content-Type": "application/json"}, b"{}"

        proxy._rate_limit_entries.clear()
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server.daemon_threads = True
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        port = server.server_address[1]
        post_result = {}

        def send_post():
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                body = b'{"messages":[]}'
                connection.request("POST", "/", body, {"Content-Type": "application/json"})
                response = connection.getresponse()
                post_result["status"] = response.status
                post_result["body"] = response.read()
            finally:
                connection.close()

        post_thread = threading.Thread(target=send_post)
        try:
            with mock.patch.object(proxy, "forward_request", side_effect=hold_forward):
                post_thread.start()
                self.assertTrue(entered_forward.wait(timeout=2))

                health_connection = HTTPConnection("127.0.0.1", port, timeout=1)
                health_connection.request("GET", "/health")
                health_response = health_connection.getresponse()
                self.assertEqual(health_response.status, 200)
                self.assertEqual(health_response.read(), b"ok\n")
                health_connection.close()

                release_forward.set()
                post_thread.join(timeout=2)
            self.assertFalse(post_thread.is_alive())
            self.assertEqual(post_result, {"status": 200, "body": b"{}"})
        finally:
            release_forward.set()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_post_releases_reservation_when_upstream_has_no_usage(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(
                proxy,
                "forward_request",
                return_value=(502, {}, b'{"error":"offline"}'),
            ):
                connection.request(
                    "POST", "/", b'{"messages":[]}', {"Content-Type": "application/json"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 502)
                response.read()

            self.assertEqual(list(proxy._rate_limit_entries), [])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_post_retains_successful_reservation_with_actual_usage(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(
                proxy,
                "forward_request",
                return_value=(200, {}, b'{"usage":{"total_tokens":17}}'),
            ):
                connection.request(
                    "POST", "/", b'{"messages":[]}', {"Content-Type": "application/json"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()

            self.assertEqual(len(proxy._rate_limit_entries), 1)
            self.assertEqual(proxy._rate_limit_entries[0]["tokens"], 17)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_post_forwards_successful_non_json_response(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        response_body = b""
        try:
            with mock.patch.object(
                proxy,
                "forward_request",
                return_value=(200, {"Content-Type": "text/event-stream"}, response_body),
            ):
                connection.request(
                    "POST", "/", b'{"messages":[]}', {"Content-Type": "application/json"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(), response_body)

            self.assertEqual(list(proxy._rate_limit_entries), [])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_post_forwards_path_method_and_safe_headers(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(
                proxy,
                "forward_request",
                return_value=(200, {"Content-Type": "application/json"}, b"{}"),
            ) as forward:
                connection.request(
                    "POST",
                    "/v1/messages?beta=true",
                    b'{"messages":[]}',
                    {
                        "Content-Type": "application/json",
                        "X-Trace-ID": "trace-1",
                        "X-Session-ID": "session-1",
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read()

            args = forward.call_args.args
            self.assertEqual(args[:3], (b'{"messages":[]}', "/v1/messages?beta=true", "POST"))
            self.assertEqual(args[3].get("X-Trace-ID"), "trace-1")
            upstream_request = proxy.make_upstream_request(
                *args[:3], client_headers=args[3]
            )
            self.assertIsNone(upstream_request.get_header("X-session-id"))
            self.assertIsNone(upstream_request.get_header("X-api-key"))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_post_rejects_absolute_proxy_target(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(proxy, "forward_request") as forward:
                connection.request(
                    "POST", "http://attacker.invalid/steal", b'{"messages":[]}',
                    {"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 400)
                forward.assert_not_called()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

    def test_post_rejects_invalid_json_without_forwarding(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.ProxyHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=2)
        try:
            with mock.patch.object(proxy, "forward_request") as forward:
                connection.request("POST", "/", b"not json", {"Content-Type": "application/json"})
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 400)
                forward.assert_not_called()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()