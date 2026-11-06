import json
import os
from unittest.mock import patch

from backend import main


def test_sentry_redacts_credential_shaped_free_text():
    redacted = main._redact_text(
        "secret=abcd1234efgh credential: hunter2xyz api_key=SUPERSECRET "
        "private_key=abc123 password=p@ssw0rd"
    )
    assert "abcd1234efgh" not in redacted
    assert "hunter2xyz" not in redacted
    assert "SUPERSECRET" not in redacted
    assert "abc123" not in redacted
    assert "p@ssw0rd" not in redacted


def test_sentry_redacts_inline_pem_private_key_blocks():
    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ\n"
        "-----END PRIVATE KEY-----"
    )
    redacted = main._redact_text(f"signing failed for key:\n{pem}")
    assert "BEGIN PRIVATE KEY" not in redacted
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ" not in redacted


def test_sentry_scrubber_removes_sensitive_request_and_local_data():
    event = {
        "request": {
            "url": "https://app.example.com/api/people/123456789?token=secret",
            "method": "POST",
            "headers": {
                "Authorization": "Bearer secret-token",
                "Cookie": "otl_session=secret",
            },
            "cookies": {"otl_session": "secret"},
            "data": {"password": "secret", "messages": ["private chat"]},
        },
        "breadcrumbs": [{"message": "Bearer secret-token"}],
        "contexts": {"custom": {"personNumber": "123456789"}},
        "extra": {"jwt": "header.payload.signature"},
        "logs": [{"message": "private chat transcript"}],
        "user": {"id": "123456789", "email": "person@example.com"},
        "stacktrace": {
            "frames": [
                {
                    "filename": "auth.py",
                    "vars": {"password": "secret", "token": "secret-token"},
                }
            ]
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "password=secret eyJhbGciOiJSUzI1NiJ9.abc.def 123456789",
                }
            ]
        },
    }
    scrubbed = main._sentry_scrub_event(event, {})
    assert scrubbed is not None
    request = scrubbed["request"]
    assert "headers" not in request
    assert "cookies" not in request
    assert "data" not in request
    assert "query" not in request["url"]
    assert "123456789" not in request["url"]
    assert "breadcrumbs" not in scrubbed
    assert "contexts" not in scrubbed
    assert "extra" not in scrubbed
    assert "logs" not in scrubbed
    assert "user" not in scrubbed
    assert "vars" not in scrubbed["stacktrace"]["frames"][0]
    exception_value = scrubbed["exception"]["values"][0]["value"]
    assert "secret" not in exception_value
    assert "123456789" not in exception_value


def test_sentry_drops_all_sensitive_flow_events_and_transactions():
    for path in (
        "/api/auth/login",
        "/api/chat",
        "/api/tts",
        "/api/stt/stream",
        "/api/otl/timecards",
    ):
        event = {"request": {"url": f"https://app.example.com{path}"}}
        assert main._sentry_scrub_event(event, {}) is None
        transaction = {"transaction": f"POST {path}", "spans": []}
        assert main._sentry_scrub_transaction(transaction, {}) is None


def test_sentry_drops_all_breadcrumbs_to_prevent_chat_text_capture():
    assert (
        main._sentry_scrub_breadcrumb(
            {"category": "httpx", "message": "POST /api/chat"}, {}
        )
        is None
    )
    assert (
        main._sentry_scrub_breadcrumb(
            {"category": "app", "message": "private chat transcript"}, {}
        )
        is None
    )


def test_sentry_transaction_scrubs_request_query_string_user_and_asgi_scope():
    transaction = {
        "transaction": "POST /api/people/lookup",
        "request": {
            "url": "https://app.example.com/api/people/lookup?personNumber=12345",
            "method": "POST",
            "headers": {"Authorization": "Bearer secret-token"},
            "cookies": {"otl_session": "secret"},
            "data": {"personNumber": "12345"},
        },
        "user": {"id": "u-1", "email": "person@example.com"},
        "tags": {"person": "12345"},
        "contexts": {
            "asgi": {
                "self": {
                    "headers": [[b"host", b"app.example.com"]],
                    "query_string": b"personNumber=12345",
                    "client": ("10.0.0.5", 5000),
                }
            },
            "trace": {"trace_id": "a" * 32, "span_id": "b" * 16},
        },
        "stacktrace": {"frames": [{"filename": "otl.py", "vars": {"token": "secret"}}]},
        "spans": [],
    }
    scrubbed = main._sentry_scrub_transaction(transaction, {})
    assert scrubbed is not None
    request = scrubbed["request"]
    assert "personNumber" not in request["url"]
    assert request["url"] == "https://app.example.com/api/people/lookup"
    assert "headers" not in request
    assert "cookies" not in request
    assert "data" not in request
    assert "user" not in scrubbed
    assert "tags" not in scrubbed
    assert "asgi" not in scrubbed["contexts"]
    # The client IP only ever lived in the ASGI scope, so dropping that scope
    # is what removes it; assert it is nowhere in the serialised payload.
    assert "10.0.0.5" not in json.dumps(scrubbed, default=str)
    # contexts.trace is what links the transaction to its errors and must stay.
    assert scrubbed["contexts"]["trace"]["trace_id"] == "a" * 32
    assert "vars" not in scrubbed["stacktrace"]["frames"][0]


def test_sentry_breadcrumb_scrubber_never_returns_a_crum():
    assert (
        main._sentry_scrub_breadcrumb({"category": "app", "message": "x"}, {}) is None
    )
    assert main._sentry_scrub_breadcrumb({}, {}) is None


def test_sentry_scrubbers_ignore_non_dict_input():
    assert main._sentry_scrub_event("not an event", {}) is None
    assert main._sentry_scrub_transaction("not an event", {}) is None
    assert main._sentry_scrub_event(None, {}) is None
    assert main._sentry_scrub_transaction(None, {}) is None


def test_sentry_sample_rate_is_clamped_and_survives_a_bad_value():
    with patch.dict(os.environ, {"RATE": "2.0"}, clear=False):
        assert main._sentry_sample_rate("RATE", 0.05, 0.1) == 0.1
    with patch.dict(os.environ, {"RATE": "-1.0"}, clear=False):
        assert main._sentry_sample_rate("RATE", 0.05, 0.1) == 0.0
    with patch.dict(os.environ, {"RATE": "not-a-number"}, clear=False):
        assert main._sentry_sample_rate("RATE", 0.05, 0.1) == 0.05


def test_sentry_profiles_are_disabled_and_samples_are_capped():
    env = {
        "SENTRY_DSN": "https://public@example.com/1",
        "SENTRY_TRACES_SAMPLE_RATE": "1.0",
        "SENTRY_PROFILES_SAMPLE_RATE": "1.0",
    }
    with (
        patch.dict(os.environ, env, clear=False),
        patch("backend.main.sentry_sdk.init") as init,
    ):
        main._initialize_sentry()
    kwargs = init.call_args.kwargs
    assert kwargs["profiles_sample_rate"] == 0.0
    assert kwargs["traces_sample_rate"] == 0.1
    assert kwargs["send_default_pii"] is False
    assert kwargs["include_local_variables"] is False
