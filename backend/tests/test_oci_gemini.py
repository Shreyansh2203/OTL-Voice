import json
import os
from unittest.mock import MagicMock, patch

import pytest

from backend.services.oci_gemini import (
    GeminiChatClient,
    _env,
    _normalize_pem,
    _service_endpoint,
    build_oci_config,
)


def test_env():
    os.environ["TEST_ENV"] = " value "
    assert _env("TEST_ENV") == "value"
    assert _env("NON_EXISTENT", "def") == "def"
    del os.environ["TEST_ENV"]
def test_normalize_pem():
    assert _normalize_pem("-----BEGIN RSA PRIVATE KEY-----\\nMIIB\\n-----END RSA PRIVATE KEY-----") == "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n"
    assert _normalize_pem("invalid") == "invalid"
@patch.dict(os.environ, {
    "OCI_REGION": "us-ashburn-1",
    "OCI_USER_OCID": "user1",
    "OCI_TENANCY_OCID": "tenancy1",
    "OCI_FINGERPRINT": "fingerprint1",
    "OCI_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\\nMIIB\\n-----END RSA PRIVATE KEY-----",
    "OCI_PRIVATE_KEY_PASSPHRASE": "pass",
    "OCI_COMPARTMENT_ID": "compartment1"
}, clear=True)
def test_build_oci_config_inline():
    config = build_oci_config()
    assert config["user"] == "user1"
    assert "key_content" in config
    assert config["pass_phrase"] == "pass"
@patch.dict(os.environ, {
    "OCI_REGION": "us-ashburn-1",
    "OCI_USER_OCID": "user1",
    "OCI_TENANCY_OCID": "tenancy1",
    "OCI_FINGERPRINT": "fingerprint1",
    "OCI_PRIVATE_KEY_PATH": "/path/to/key",
    "OCI_COMPARTMENT_ID": "compartment1"
}, clear=True)
def test_build_oci_config_file():
    config = build_oci_config()
    assert config["key_file"] == "/path/to/key"
@patch.dict(os.environ, {
    "OCI_REGION": "us-ashburn-1",
    "OCI_USER_OCID": "user1",
    "OCI_TENANCY_OCID": "tenancy1",
    "OCI_FINGERPRINT": "fingerprint1",
    "OCI_COMPARTMENT_ID": "compartment1"
}, clear=True)
def test_build_oci_config_missing_key():
    with pytest.raises(RuntimeError):
        build_oci_config()
@patch("backend.services.oci_gemini.oci.config.from_file")
@patch.dict(os.environ, {}, clear=True)
def test_build_oci_config_fallback(mock_from_file):
    mock_from_file.return_value = {"region": "fallback"}
    config = build_oci_config()
    assert config["region"] == "fallback"
def test_service_endpoint():
    assert _service_endpoint("us-ashburn-1") == "https://inference.generativeai.us-ashburn-1.oci.oraclecloud.com"
    os.environ["OCI_SERVICE_ENDPOINT"] = "http://custom"
    assert _service_endpoint("us-ashburn-1") == "http://custom"
    del os.environ["OCI_SERVICE_ENDPOINT"]
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {
    "OCI_COMPARTMENT_ID": "compartment1",
    "OCI_REGION": "us-ashburn-1",
    "OCI_USER_OCID": "user1",
    "OCI_TENANCY_OCID": "tenancy1",
    "OCI_FINGERPRINT": "fingerprint1",
    "OCI_PRIVATE_KEY": "invalid_key",
}, clear=True)
def test_client_initialization(mock_client):
    client = GeminiChatClient()
    assert client.compartment_id == "compartment1"
@patch("backend.services.oci_gemini.oci.config.from_file")
@patch.dict(os.environ, {}, clear=True)
def test_client_init_missing_compartment(mock_from_file):
    mock_from_file.return_value = {"region": "us-ashburn-1"}
    with pytest.raises(RuntimeError, match="OCI_COMPARTMENT_ID"):
        GeminiChatClient()
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_complete_and_extract(mock_client):
    client = GeminiChatClient()
    mock_resp = MagicMock()
    mock_resp.data.chat_response.choices = [
        MagicMock(message=MagicMock(content=[MagicMock(text="response text")]))
    ]
    client.client.chat.return_value = mock_resp
    res = client.complete("sys", [{"role": "user", "content": "hello"}])
    assert res == "response text"
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_complete_fallback_json(mock_client):
    client = GeminiChatClient()
    mock_resp = MagicMock()
    del mock_resp.data.chat_response
    mock_resp.data.__str__.return_value = json.dumps({"text": "fallback text", "nested": [{"text": " 2"}]})
    client.client.chat.return_value = mock_resp
    res = client.complete("sys", [])
    assert res == "fallback text 2"
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_complete_fallback_empty(mock_client):
    client = GeminiChatClient()
    mock_resp = MagicMock()
    del mock_resp.data.chat_response
    mock_resp.data.__str__.return_value = "invalid json"
    client.client.chat.return_value = mock_resp
    assert client.complete("sys", []) == ""
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_stream_success(mock_client):
    client = GeminiChatClient()
    mock_resp = MagicMock()
    mock_event1 = MagicMock(data=json.dumps({"message": {"content": [{"text": "stream"}]}}))
    mock_event2 = MagicMock(data="[DONE]")
    mock_resp.data.events.return_value = [MagicMock(data=""), mock_event1, mock_event2]
    client.client.chat.return_value = mock_resp
    res = list(client.stream("sys", []))
    assert res == ["stream"]
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_stream_fallback(mock_client):
    client = GeminiChatClient()
    client.client.chat.side_effect = Exception("stream fail")
    client.complete = MagicMock(return_value="fallback complete")
    res = list(client.stream("sys", []))
    assert res == ["fallback complete"]
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_stream_partial_error(mock_client):
    client = GeminiChatClient()
    mock_resp = MagicMock()
    def raise_err():
        yield MagicMock(data=json.dumps({"text": "part1"}))
        raise Exception("error after some data")
    mock_resp.data.events.return_value = raise_err()
    client.client.chat.return_value = mock_resp
    res = list(client.stream("sys", []))
    assert res == ["part1"]
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_stream_empty_events(mock_client):
    client = GeminiChatClient()
    mock_resp = MagicMock()
    mock_resp.data.events.return_value = [MagicMock(data=""), MagicMock(data=json.dumps({"other": "no text"}))]
    client.client.chat.return_value = mock_resp
    client.complete = MagicMock(return_value="fallback")
    res = list(client.stream("sys", []))
    assert res == ["fallback"]
def test_extract_delta():
    assert GeminiChatClient._extract_delta(json.dumps({"text": "raw"})) == "raw"
    assert GeminiChatClient._extract_delta(json.dumps({"message": {"content": [{"other": "val"}]}})) == ""
    assert GeminiChatClient._extract_delta(json.dumps({"other": "val"})) == ""
    assert GeminiChatClient._extract_delta("invalid") == ""
@patch("backend.services.oci_gemini.GenerativeAiInferenceClient")
@patch.dict(os.environ, {"OCI_COMPARTMENT_ID": "c1", "OCI_REGION": "r1", "OCI_USER_OCID": "ocid1.user.oc1..aaaaaa", "OCI_TENANCY_OCID": "ocid1.tenancy.oc1..bbbbb", "OCI_FINGERPRINT": "00:11:22:33:44", "OCI_PRIVATE_KEY": "k1"}, clear=True)
def test_ping(mock_client):
    with patch.object(GeminiChatClient, 'complete', return_value="OK"):
        client = GeminiChatClient()
        assert client.ping() == "OK"