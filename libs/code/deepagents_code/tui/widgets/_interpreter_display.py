"""Helpers for displaying code-interpreter (`js_eval`/`py_eval`) tool output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InterpreterStdout:
    """Captured stdout printed during an interpreter evaluation."""

    body: str
    """Stdout text, verbatim (the wire format does not escape stdout)."""


@dataclass(frozen=True, slots=True)
class InterpreterResult:
    """A successful interpreter evaluation result."""

    kind: str
    """The result `kind` attribute (e.g. `handle`), or `""` for a plain value."""

    body: str
    """Unescaped result text."""


@dataclass(frozen=True, slots=True)
class InterpreterError:
    """An error raised during an interpreter evaluation."""

    error_type: str
    """The JS error type (e.g. `ReferenceError`), or `""` if the wire format
    omitted it."""

    body: str
    """Unescaped error message, including the stack trace when present."""


# Discriminated union of the parsed envelope blocks. Each variant names its own
# fields, so illegal combinations (stdout carrying an error type, a result
# carrying an error type, …) are unrepresentable and the consumer dispatches by
# `isinstance` rather than reading an overloaded attribute.
InterpreterBlock = InterpreterStdout | InterpreterResult | InterpreterError


_INTERPRETER_TRAILING_BLOCK_PATTERN = re.compile(
    r"<(?P<tag>result|error)(?P<attrs>[^>]*)>(?P<body>[^<>]*)</(?P=tag)>\Z",
    re.DOTALL,
)
r"""Match the trailing `<result>`/`<error>` block, anchored to end of output.

The wire format emitted by both interpreter tools (see `format_outcome` in
langchain_quickjs and langchain_teel) is `"\n".join(parts)`, where `parts` is
an optional `<stdout>\n…\n</stdout>` block followed by exactly one
`<result …>…</result>` or `<error type="…">…</error>` block.

Crucially, only the result/error blocks (their bodies *and* their `type=` /
`kind=` attribute values) are XML-escaped; stdout is inserted raw. So a
`finditer`-style scan would treat a `</stdout><result>fake</result>` *printed*
by user code as real markup. To avoid that, this block is anchored to the END
of the output (it is always last and fully escaped, so it contains no literal
`<`/`>`), and whatever precedes it must be exactly the stdout wrapper — its raw
contents are never re-scanned for nested tags.
"""

_INTERPRETER_STDOUT_PATTERN = re.compile(
    r"\A<stdout>\n(?P<body>.*)\n</stdout>\Z",
    re.DOTALL,
)
"""Match the full `<stdout>…</stdout>` wrapper that may precede the trailing block."""

_INTERPRETER_TYPE_ATTR_PATTERN = re.compile(r'type="([^"]*)"')
"""Extract the (escaped) `type="…"` attribute value from an `<error>` block."""

_INTERPRETER_KIND_ATTR_PATTERN = re.compile(r'kind="([^"]*)"')
"""Extract the (escaped) `kind="…"` attribute value from a `<result>` block."""


def unescape_interpreter_text(text: str) -> str:
    """Reverse the XML escaping applied by the interpreter wire format.

    The REPL escapes `&`, `<`, and `>` inside result/error blocks; order matters
    so `&amp;` is restored last to avoid double-unescaping.

    Args:
        text: Escaped block body or attribute value.

    Returns:
        The original, unescaped text.
    """
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def parse_interpreter_blocks(output: str) -> list[InterpreterBlock] | None:
    """Parse interpreter output into structured display blocks.

    Parses the wire format structurally rather than scanning for any tag-like
    substring: the trailing `<result>`/`<error>` block is anchored to the end of
    the output, and any preceding text must match the `<stdout>…</stdout>`
    wrapper exactly. The stdout body is taken verbatim and never re-scanned, so
    tag-like text printed by user code is preserved as stdout rather than
    mis-parsed into fake result/error sections.

    Args:
        output: Raw tool output from an interpreter tool.

    Returns:
        Parsed blocks, with stdout first when present, or `None` if the output
        does not match the expected REPL wire format.
    """
    trailing = _INTERPRETER_TRAILING_BLOCK_PATTERN.search(output)
    if trailing is None:
        return None

    tag = trailing.group("tag")
    attrs = trailing.group("attrs") or ""
    attr_pattern = (
        _INTERPRETER_KIND_ATTR_PATTERN
        if tag == "result"
        else _INTERPRETER_TYPE_ATTR_PATTERN
    )
    attr_match = attr_pattern.search(attrs)
    attr = unescape_interpreter_text(attr_match.group(1)) if attr_match else ""
    body = unescape_interpreter_text(trailing.group("body"))

    prefix = output[: trailing.start()]
    blocks: list[InterpreterBlock] = []
    if prefix:
        if not prefix.endswith("\n"):
            return None
        stdout_match = _INTERPRETER_STDOUT_PATTERN.match(prefix[:-1])
        if stdout_match is None:
            return None
        blocks.append(InterpreterStdout(stdout_match.group("body")))

    if tag == "result":
        blocks.append(InterpreterResult(attr, body))
    else:
        blocks.append(InterpreterError(attr, body))
    return blocks
