"""Bounded data-literal reader. It does not evaluate JavaScript or Python."""

from __future__ import annotations

import ast
import re
from typing import Any

_TOKEN = re.compile(
    r"\s+|//[^\n]*|/\*[\s\S]*?\*/|"
    r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|"
    r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"[A-Za-z_$][\w$]*|[{}\[\]:,;+\-/]"
)


def read_object(source: str) -> dict[str, Any]:
    source = source[source.index("var eddb =") + len("var eddb =") :]
    tokens = []
    position = 0
    for match in _TOKEN.finditer(source):
        if match.start() != position:
            raise ValueError("Unsupported reference syntax")
        position = match.end()
        token = match.group()
        if not token.isspace() and not token.startswith(("//", "/*")):
            tokens.append(token)
    if position != len(source) or len(tokens) > 250_000:
        raise ValueError("Invalid or oversized reference literal")
    cursor = 0

    def value(depth: int = 0) -> Any:
        nonlocal cursor
        if depth > 64 or cursor >= len(tokens):
            raise ValueError("Invalid reference nesting")
        token = tokens[cursor]
        cursor += 1
        if token in {"{", "["}:
            result: Any = {} if token == "{" else []
            end = "}" if token == "{" else "]"
            while tokens[cursor] != end:
                if token == "{":
                    key = tokens[cursor]
                    cursor += 1
                    key = str(ast.literal_eval(key)) if key[0] in "'\"" else key
                    if tokens[cursor] != ":":
                        raise ValueError("Expected reference property")
                    cursor += 1
                    result[key] = value(depth + 1)
                else:
                    result.append(value(depth + 1))
                if tokens[cursor] == ",":
                    cursor += 1
                elif tokens[cursor] != end:
                    raise ValueError("Expected reference separator")
            cursor += 1
            return result
        if token[0] in "'\"":
            return ast.literal_eval(token)
        if token in {"null", "NaN", "Infinity", "undefined"}:
            return None
        if token in {"true", "false"}:
            return token == "true"
        sign = 1
        if token in {"-", "+"}:
            sign = -1 if token == "-" else 1
            token = tokens[cursor]
            cursor += 1
        if not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token):
            raise ValueError("Executable reference expression is forbidden")
        number: float | int = (
            float(token) if any(c in token for c in ".eE") else int(token)
        )
        number *= sign
        if cursor < len(tokens) and tokens[cursor] == "/":
            cursor += 1
            denominator = value(depth + 1)
            if not isinstance(denominator, (int, float)):
                raise ValueError("Invalid literal ratio")
            return number / denominator if denominator else None
        return number

    result = value()
    if tokens[cursor:] != [";"] or not isinstance(result, dict):
        raise ValueError("Reference must contain exactly one data object")
    return result
