"""Programmatic tool calling (PTC) support for `CodeInterpreterMiddleware`.

PTC exposes the agent's LangChain tools inside the Python REPL as
`tools.<name>(input)` *synchronous* functions. Instead of issuing N serial
tool calls, the model writes one `eval` that loops / chains tools in-code:

    results = [tools.search({"query": q}) for q in ("foo", "bar")]

Two pieces live here:

- filtering — turn the live agent toolset into the subset exposed to PTC
- prompt rendering — render a short Python API-reference block describing
    each exposed tool, so the model knows the call shape

The bridge that actually invokes each tool lives in `_repl.py` next to the
rest of the REPL wiring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from langchain_quickjs import _prompt

if TYPE_CHECKING:
    from collections.abc import Sequence


PTCOption = list[str | BaseTool]

_RESERVED_SUBAGENT_TASK_NAME = "task"

_TASK_IN_PTC_MSG = (
    "The subagent `task` tool cannot be exposed via `ptc`. It is always "
    "available as the top-level `task()` function; also exposing it under "
    "the `tools.*` namespace would create a second, conflicting dispatch path "
    'that drops `response_schema`. Remove "task" from `ptc`.'
)


def filter_tools_for_ptc(
    tools: Sequence[BaseTool],
    config: PTCOption,
    *,
    self_tool_name: str,
) -> list[BaseTool]:
    """Return the subset of `tools` exposed inside the REPL.

    `self_tool_name` is the REPL's own tool name; it is *always* excluded to
    prevent the model from recursing `tools.eval("tools.eval(...)")`. If the
    model wants a nested eval, it can just write nested code in one call —
    that's the whole point of PTC.

    `config` is allowlist-only:

    - `str` entries: expose matching tool names from `tools`.
    - `BaseTool` entries: expose those tools directly (minus `self_tool_name`).

    Mixed lists are supported and merged. Explicit `BaseTool` entries are
    included first, then name-matched agent tools are appended. Duplicate tool
    names are deduplicated.

    The subagent `task` tool is reserved and may not appear in `config` (by
    name or instance) — it is always available as the `task()` global, so a
    `tools.task` PTC variant would be a conflicting, degraded duplicate. A
    `"task"` entry raises `ValueError`.

    Warning:
        PTC tool calls execute through the REPL bridge and currently do not
        respect `interrupt_on` / HITL approval hooks for each individual tool
        invocation.
    """
    if isinstance(config, list):
        explicit_tools: list[BaseTool] = []
        allow_names: set[str] = set()
        for entry in config:
            if isinstance(entry, BaseTool):
                if entry.name == _RESERVED_SUBAGENT_TASK_NAME:
                    raise ValueError(_TASK_IN_PTC_MSG)
                if entry.name != self_tool_name:
                    explicit_tools.append(entry)
                continue
            if isinstance(entry, str):
                if entry == _RESERVED_SUBAGENT_TASK_NAME:
                    raise ValueError(_TASK_IN_PTC_MSG)
                allow_names.add(entry)
                continue
            msg = "ptc list entries must be str or BaseTool"
            raise TypeError(msg)
        selected = [
            *explicit_tools,
            *[t for t in tools if t.name != self_tool_name and t.name in allow_names],
        ]
        deduped: list[BaseTool] = []
        seen_names: set[str] = set()
        for tool in selected:
            if tool.name in seen_names:
                continue
            seen_names.add(tool.name)
            deduped.append(tool)
        selected = deduped
        _raise_on_invalid_ptc_tools(selected)
        return selected
    msg = (
        "Unsupported `ptc` config type. "
        "Use a list of tool names, list of BaseTool instances, or disable PTC."
    )
    raise TypeError(msg)


def is_valid_python_identifier(name: str) -> bool:
    """Return whether `name` is a valid, non-keyword Python identifier."""
    return _prompt.is_valid_python_identifier(name)


def is_valid_ptc_tool_name(name: str) -> bool:
    """Return whether a tool can be exposed as `tools.<name>`."""
    return _prompt.is_valid_ptc_tool_name(name)


def _raise_on_invalid_ptc_tools(tools: Sequence[BaseTool]) -> None:
    for tool in tools:
        if is_valid_python_identifier(tool.name):
            continue
        msg = (
            f"PTC tool name {tool.name!r} cannot be exposed as a Python "
            "attribute on the `tools` namespace. Tool names must be valid, "
            "non-keyword Python identifiers."
        )
        raise ValueError(msg)


def render_ptc_prompt(tools: Sequence[BaseTool], *, tool_name: str = "eval") -> str:
    """Build the `tools` namespace section of the system prompt."""
    if not tools:
        return ""
    _raise_on_invalid_ptc_tools(tools)
    return _prompt.render_ptc_prompt(tools, tool_name=tool_name)
