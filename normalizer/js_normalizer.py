import base64
import re
from pathlib import Path

try:
    import jsbeautifier as _jsb
    _BEAUTIFIER_OPTS = _jsb.default_options()
    _BEAUTIFIER_OPTS.unescape_strings = True
    _HAS_BEAUTIFIER = True
except ImportError:
    _HAS_BEAUTIFIER = False

# atob("base64==") or btoa("...")
_ATOB_RE = re.compile(r'atob\s*\(\s*["\']([A-Za-z0-9+/=]{8,})["\'\s]*\)')

# \x41\x42\x43 sequences (4+ consecutive hex escapes)
_HEX_ESC_RE = re.compile(r'(?:\\x[0-9a-fA-F]{2}){4,}')

# "foo" + "bar"  →  "foobar"  (handles optional whitespace around +)
_STR_CONCAT_RE = re.compile(r'"([^"\\]*)"\s*\+\s*"([^"\\]*)"')
_STR_CONCAT_SQ_RE = re.compile(r"'([^'\\]*)'\s*\+\s*'([^'\\]*)'")


def _decode_atob(m: re.Match) -> str:
    try:
        decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
        return f'"{decoded}"'
    except Exception:
        return m.group(0)


def _decode_hex_escape(m: re.Match) -> str:
    try:
        raw = m.group(0).replace("\\x", "")
        return f'"{bytes.fromhex(raw).decode("utf-8", errors="replace")}"'
    except Exception:
        return m.group(0)


def _flatten_concat(text: str, max_passes: int = 5) -> str:
    for _ in range(max_passes):
        prev = text
        text = _STR_CONCAT_RE.sub(lambda m: f'"{m.group(1)}{m.group(2)}"', text)
        text = _STR_CONCAT_SQ_RE.sub(lambda m: f"'{m.group(1)}{m.group(2)}'", text)
        if text == prev:
            break
    return text


def normalize(input_path: Path, output_path: Path) -> bool:
    try:
        content = input_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False

    if _HAS_BEAUTIFIER:
        try:
            content = _jsb.beautify(content, _BEAUTIFIER_OPTS)
        except Exception:
            pass

    content = _ATOB_RE.sub(_decode_atob, content)
    content = _HEX_ESC_RE.sub(_decode_hex_escape, content)
    content = _flatten_concat(content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content.encode("utf-8", errors="replace"))
    return True
