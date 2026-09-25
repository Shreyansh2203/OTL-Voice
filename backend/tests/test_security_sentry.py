import os
from unittest.mock import patch

from backend import main


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
