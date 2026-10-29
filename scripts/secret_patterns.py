"""The secret patterns of `secret-patterns.txt` as Python regular expressions.

Used by `secret_output_scan.py` and `tool_timing.py`; importing it has no side effects.
  redact(text, cap=CAP) -> (text, names)   each match that is not a placeholder is replaced by [REDACTED:<name>]; names are the patterns that hit
  find(text)            -> names           the same scan, text discarded
Only the last `cap` characters are scanned (None scans all); what comes before stays byte for byte.
"""
import os
import re
import warnings

CAP = 200_000
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret-patterns.txt")
_patterns = None


def _python(pattern):
    return pattern.replace("[:space:]", "\\s")  # the shared ERE has the POSIX class, python re has none


def load(path=_PATH):
    """[(name, pattern, placeholder pattern or None)] from the patterns file."""
    patterns = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a `[` inside a class is literal in ERE and a nested-set warning in python re
        with open(path, encoding="utf-8") as lines:
            for line in lines:
                if not line.strip() or line.startswith("#"):
                    continue
                name, pattern, *placeholder = line.rstrip("\n").split("\t") + [""]
                patterns.append((name, re.compile(_python(pattern)), re.compile(_python(placeholder[0])) if placeholder[0] else None))
    return patterns


def redact(text, cap=CAP):
    """(text with every secret span replaced by [REDACTED:<name>], the names that matched, in pattern order)."""
    global _patterns
    if _patterns is None:
        _patterns = load()
    head, tail = (text[:-cap], text[-cap:]) if cap else ("", text)
    names = []
    for name, pattern, placeholder in _patterns:
        def replace(match, name=name, placeholder=placeholder):
            span = match.group(0)
            if placeholder and placeholder.search(span):
                return span
            if name not in names:
                names.append(name)
            # a pattern can swallow the whitespace around a secret; keep it
            return span[:len(span) - len(span.lstrip())] + f"[REDACTED:{name}]" + span[len(span.rstrip()):]
        tail = pattern.sub(replace, tail)
    return head + tail, names


def find(text, cap=CAP):
    return redact(text, cap)[1]
