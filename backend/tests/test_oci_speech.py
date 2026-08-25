from unittest.mock import MagicMock, patch

import oci
import pytest

from backend.services.oci_speech import (
    SpeechClient,
    _rate_to_percent,
    _speech_endpoint,
    clean_for_speech,
)


def test_speech_endpoint(monkeypatch):
    monkeypatch.delenv("OCI_SPEECH_ENDPOINT", raising=False)
    assert _speech_endpoint("us-ashburn-1") == "https://speech.aiservice.us-ashburn-1.oci.oraclecloud.com"
    monkeypatch.setenv("OCI_SPEECH_ENDPOINT", "https://custom.endpoint")
    assert _speech_endpoint("us-ashburn-1") == "https://custom.endpoint"
def test_rate_to_percent():
    assert _rate_to_percent(1.0) == "100%"
    assert _rate_to_percent(0.1) == "20%"
    assert _rate_to_percent(4.0) == "300%"
    assert _rate_to_percent(1.5) == "150%"
def test_clean_for_speech():
    assert clean_for_speech(None) == ""
    assert clean_for_speech("") == ""
    assert clean_for_speech("```\ncode\n```") == ""
    assert clean_for_speech("[link](url)") == "link"
    assert clean_for_speech("`code`") == "code"
    assert clean_for_speech("~~strike~~") == "strike"
    assert clean_for_speech("---\n***") == ""
    assert clean_for_speech("## heading") == "heading"
    assert clean_for_speech("> quote") == "quote"
    assert clean_for_speech("- bullet\n* item") == "bullet\nitem"
    assert clean_for_speech("**bold** and *italic*") == "bold and italic"
    assert clean_for_speech("_underscore_ and __strong__") == "underscore and strong"
    assert clean_for_speech("var_name and ABC_123") == "var_name and ABC_123"
    assert clean_for_speech("a ** b * c") == "a b c"
    assert clean_for_speech("multi  space") == "multi space"
    assert clean_for_speech("multi\n\nline") == "multi\nline"
@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..test")
    monkeypatch.setenv("OCI_REGION", "us-ashburn-1")
@patch("backend.services.oci_speech.build_oci_config")
@patch("backend.services.oci_speech.AIServiceSpeechClient")
def test_speech_client_init(mock_client, mock_build, mock_env, monkeypatch):
    mock_build.return_value = {"region": "us-ashburn-1"}
    client = SpeechClient()
    assert client.compartment_id == "ocid1.compartment.oc1..test"
    assert client.region == "us-ashburn-1"
    monkeypatch.delenv("OCI_COMPARTMENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="OCI_COMPARTMENT_ID is not set in your .env."):
        SpeechClient()
@patch("backend.services.oci_speech.build_oci_config")
@patch("backend.services.oci_speech.AIServiceSpeechClient")
def test_speech_client_properties(mock_client, mock_build, mock_env, monkeypatch):
    mock_build.return_value = {}
    monkeypatch.setenv("TTS_OUTPUT_FORMAT", "MP3")
    client = SpeechClient()
    assert client.mime == "audio/mp3"
    monkeypatch.setenv("TTS_OUTPUT_FORMAT", "OGG")
    client = SpeechClient()
    assert client.mime == "audio/ogg"
    monkeypatch.setenv("TTS_OUTPUT_FORMAT", "PCM")
    client = SpeechClient()
    assert client.mime == "audio/wav"
    monkeypatch.setenv("TTS_OUTPUT_FORMAT", "UNKNOWN")
    client = SpeechClient()
    assert client.mime == "audio/mp3"
    client.voice_id = "Brian"
    client.model_name = "TTS_2_NATURAL"
    client.language_code = "en-US"
    client.sample_rate = 22050
    client.output_format = "MP3"
    assert client.signature == "Brian:TTS_2_NATURAL:en-US:22050:MP3"
@patch("backend.services.oci_speech.build_oci_config")
@patch("backend.services.oci_speech.AIServiceSpeechClient")
def test_speech_client_details(mock_client, mock_build, mock_env):
    mock_build.return_value = {}
    client = SpeechClient()
    details = client._details("hello", "TEXT")
    assert details.text == "hello"
    assert details.configuration.speech_settings.text_type == "TEXT"
@patch("backend.services.oci_speech.build_oci_config")
@patch("backend.services.oci_speech.AIServiceSpeechClient")
def test_speech_client_call(mock_client, mock_build, mock_env):
    mock_build.return_value = {}
    client = SpeechClient()
    mock_response = MagicMock()
    mock_response.data.content = b"content_bytes"
    client.client.synthesize_speech.return_value = mock_response
    assert client._call(MagicMock()) == b"content_bytes"
    mock_response = MagicMock()
    del mock_response.data.content
    mock_response.data.raw.read.return_value = b"raw_bytes"
    client.client.synthesize_speech.return_value = mock_response
    assert client._call(MagicMock()) == b"raw_bytes"
    mock_response = MagicMock()
    mock_response.data.content = None
    mock_response.data.raw.read.return_value = b"raw_bytes2"
    client.client.synthesize_speech.return_value = mock_response
    assert client._call(MagicMock()) == b"raw_bytes2"
@patch("backend.services.oci_speech.build_oci_config")
@patch("backend.services.oci_speech.AIServiceSpeechClient")
def test_speech_client_synthesize(mock_client_class, mock_build, mock_env):
    mock_build.return_value = {}
    client = SpeechClient()
    mock_response = MagicMock()
    mock_response.data.content = b"audio"
    client.client.synthesize_speech.return_value = mock_response
    assert client.synthesize("") == b""
    assert client.synthesize("```code```") == b""
    assert client.synthesize("hello", 1.0) == b"audio"
    assert client.synthesize("hello", 1.5) == b"audio"
    client.client.synthesize_speech.side_effect = [
        oci.exceptions.ServiceError(status=500, code="500", message="error", headers={}), 
        mock_response
    ]
    assert client.synthesize("hello", 1.5) == b"audio"