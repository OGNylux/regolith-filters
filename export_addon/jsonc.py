"""JSON-with-comments helpers shared across the filter."""

import json


def strip_jsonc(text):
    """Remove // and /* */ comments from JSON text (string-aware)."""
    out = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def try_load_json(text):
    """Parse JSON (tolerating // and /* */ comments), or return None."""
    try:
        return json.loads(text)
    except ValueError:
        try:
            return json.loads(strip_jsonc(text))
        except ValueError:
            return None


def minify_json(raw):
    """Return minified JSON bytes, or None if the file can't be parsed."""
    text = raw.decode("utf-8-sig")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:
            obj = json.loads(strip_jsonc(text))
        except json.JSONDecodeError:
            return None
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
