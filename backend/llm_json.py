"""Tolerant parser for JSON produced by LLMs: code fences, prose around the object, raw newlines / unescaped double quotes inside strings,
trailing commas and answers cut short (max_tokens / dropped stream) are repaired instead of failing."""
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_OPEN_AFTER = set("{[,:")
_CLOSE_BEFORE = set(",:}]")
_CLOSER = {"{": "}", "[": "]"}


def parse_llm_json(text):
    """Returns the first JSON object found in `text` as a dict, or None."""
    if not text:
        return None
    t = text.strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    start = t.find("{")
    if start < 0:
        return None
    t = t[start:]
    end = t.rfind("}")
    for cand in ([t[:end + 1]] if end > 0 else []) + [t]:
        for variant in (cand, _newlines(cand), _inner_quotes(cand), _inner_quotes(_newlines(cand))):
            d = _loads(variant)
            if d is not None:
                return d
    for variant in (t, _inner_quotes(_newlines(t))):
        d = _close_truncated(variant)
        if d is not None:
            return d
    return None


def _loads(s: str):
    for v in (s, _TRAILING_COMMA.sub(r"\1", s)):
        try:
            d = json.loads(v)
        except ValueError:
            continue
        if isinstance(d, dict):
            return d
    return None


def _newlines(s: str) -> str:
    return re.sub(r"(?<=[^\\])\n", " ", s)


def _inner_quotes(s: str) -> str:
    """Turns double quotes that cannot be string delimiters (not next to a structural character) into single quotes."""
    out, in_str, i, n = [], False, 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and in_str and i + 1 < n:
            out.append(ch)
            out.append(s[i + 1])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
                out.append(ch)
            else:
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                if j >= n or s[j] in _CLOSE_BEFORE:
                    in_str = False
                    out.append(ch)
                else:
                    out.append("'")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _close_truncated(s: str):
    """Cuts the text back to the last complete item (a comma or a closing bracket outside strings) and closes the open containers."""
    stack, points, in_str, i, n = [], [], False, 0, len(s)
    while i < n:
        ch = s[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            points.append((i + 1, "".join(_CLOSER[c] for c in reversed(stack))))
        elif ch == ",":
            points.append((i, "".join(_CLOSER[c] for c in reversed(stack))))
        i += 1
    for pos, closers in reversed(points[-40:]):
        d = _loads(s[:pos] + closers)
        if d is not None:
            return d
    return None
