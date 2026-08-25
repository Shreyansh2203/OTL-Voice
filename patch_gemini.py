utf-8with open('backend/services/oci_gemini.py', 'r', encoding='utf-8') as f:
    content = f.read()
old_str = '''            else:
                break
    raise last_exception'''
new_str = '''            else:
                break
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Retry loop failed without an exception")'''
content = content.replace(old_str, new_str)
with open('backend/services/oci_gemini.py', 'w', encoding='utf-8') as f:
    f.write(content)