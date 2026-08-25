utf-8import re
with open('backend/services/oci_speech.py', 'r', encoding='utf-8') as f:
    content = f.read()
old_listener = '''except ImportError:
    class _STTListener:
        pass'''
new_listener = '''except ImportError:
    class _DummySTTListener:
        pass
    _STTListener = _DummySTTListener  # type: ignore'''
content = content.replace(old_listener, new_listener)
old_ssml = '''            try:
                return self._call(self._details(ssml_payload, "SSML"))
            except oci.exceptions.ServiceError:
                pass # fallback to text
        if abs(rate - 1.0) < 1e-3:'''
new_ssml = '''            try:
                import xml.etree.ElementTree as ET
                ET.fromstring(ssml_payload)
                return self._call(self._details(ssml_payload, "SSML"))
            except (oci.exceptions.ServiceError, Exception):
                import re
                clean = re.sub(r'<[^>]+>', '', clean) # fallback to text without tags
        if abs(rate - 1.0) < 1e-3:'''
content = content.replace(old_ssml, new_ssml)
with open('backend/services/oci_speech.py', 'w', encoding='utf-8') as f:
    f.write(content)