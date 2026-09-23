"""Prompt/rendering helpers for REPL and PTC system prompts."""

from __future__ import annotations

import contextlib
import inspect
import json
import keyword
import re
from typing import TYPE_CHECKING, Any, Literal, get_type_hints

from pydantic import TypeAdapter

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool

_REPL_SYSTEM_PROMPT_TEMPLATE = (
    "### Python interpreter\n\n"
    "{repl_intro_line}\n\n"
    "{state_persistence_line}\n"
    "- The value of the last expression in a call is returned to you as the "
    "result, like a REPL. Put the variable holding your answer on the last "
    "line.\n"
    "- Calls are synchronous: `task(...)` and `tools.<name>(...)` return their "
    "value directly. Write plain sequential Python; independent calls are "
    "started ahead of time and run concurrently for you, so there is no need "
    "for threads or `asyncio`.\n"
    "- Sandbox: CPython 3.12 compiled to WebAssembly with the standard library, "
    "but no filesystem, network, subprocesses, or threads.\n"
    "{side_effects_line}\n"
    "- Timeout: {timeout}s of computation per call (time spent waiting on "
    "`task` or `tools.*` is not counted). Memory: {memory_limit_mb} MB. "
    "Exceeding either resets the interpreter state.\n"
    "- `print(...)` output is captured and returned in a `<stdout>` block, but "
    "it is capped and truncated; return real results via the last expression."
)
_SUBAGENT_SYSTEM_PROMPT_TEMPLATE = """

### Dispatching Subagents with `task`

`task` is your primitive for running configured subagents from inside the
Python interpreter. Your job here is to DISTRIBUTE work, not to do it yourself:
write Python that fans work out to subagents and assembles their results. You
handle the orchestration - iteration, filtering, deduplication, multi-stage
flow, and synthesis - in plain Python.

#### The primitive

```python
task(
    description,           # full autonomous task prompt
    subagent_type,         # configured subagent name
    label=None,            # optional short UI label for this dispatch
    response_schema=None,  # optional JSON Schema (dict) for structured output
)  # -> the subagent's final result
```

`task` runs a full agentic loop for the selected configured subagent and
returns its final result. `subagent_type` is required; use one of the
configured subagent names.

`description` is the only prompt the subagent receives for this dispatch. Make
it complete: the goal, the constraints, what to inspect, and the exact shape or
level of detail you expect back. Give context as locators — file paths and
symbol names — not as pasted file contents. Each dispatch is stateless from the
caller's perspective; you cannot send follow-up messages to the same run.

`label` is optional: when provided it is shown in the live progress UI instead
of the default description-derived fallback. It is not sent to the subagent.

`response_schema` is optional, but set it on any dispatch whose result feeds
later code. A deterministic, typed shape is what lets you compose the next
stage reliably — index it, sort it, compare fields, branch on it, merge it —
instead of parsing free-form text. When provided, the returned value is already
a typed Python value matching the schema; do not call `json.loads` unless the
subagent intentionally returned a JSON string.

#### Approval model

`task` dispatches from inside the already-running `{tool_name}` call. It does
not route through the parent agent's `ToolNode`-managed `task` tool and does not
trigger parent-level `interrupt_on` / HITL approval for each dispatch. If you
need approval before launching a subagent from the parent, use the normal
`task` tool outside `{tool_name}`, or ensure the `{tool_name}` call itself is
approval-gated.

#### Fan out with plain loops

Write the fan-out as an ordinary loop or comprehension. Dispatches whose inputs
are already known start concurrently in the background, so a loop over ten
files does not take ten times as long.

```python
files = ["/src/a.py", "/src/b.py", "/src/c.py"]  # found while exploring
reviewed = [
    {
        "file": file,
        **task(
            f"Read {file} and review it for SQL injection. Cite line numbers.",
            "reviewer",
            response_schema={
                "type": "object",
                "properties": {
                    "findings": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["findings"],
            },
        ),
    }
    for file in files
]
```

#### Explore with your own tools first, then distribute

Use your normal file tools to read, list, glob, and grep BEFORE you write the
orchestration code. Never write `{tool_name}` code that spawns a subagent just
to read a file or list a directory; do that yourself with a direct tool call.
Hand each subagent a locator (a path), not a pasted payload.

#### Compose multiple stages

Filter the list in Python between passes: a cheap classification first, then
deeper dispatches only for the items that warrant them.

```python
tagged = [
    {"file": file, **task(f"Classify {file}.", "reviewer", response_schema={
        "type": "object",
        "properties": {"kind": {"type": "string"}, "risky": {"type": "boolean"}},
        "required": ["kind", "risky"],
    })}
    for file in files
]
risky = [it for it in tagged if it["kind"] == "handler" and it["risky"]]
deep = [
    {**it, "review": task(f"Deep review of {it['file']}.", "reviewer")}
    for it in risky
]
```

#### Return results via the last expression, not `print`

The value of the last expression in a `{tool_name}` call is returned to you.
Make that final expression the variable holding your result. Keep large
intermediate sets in variables and return only a compact summary or a small
slice.

#### Reuse what earlier calls left in scope

Every top-level variable, function, and class you define is available in your
next `{tool_name}` call (while state persists). Reference earlier results by
name instead of re-typing them as a literal.

#### When the user asks for a "workflow"

If the user's request mentions running a "workflow", fan the work out to
subagents rather than doing it all yourself: explore with your own tools, then
write Python in the `{tool_name}` tool that dispatches subagents with `task(...)`
and assembles their results.
"""


def render_repl_system_prompt(
    *,
    tool_name: str,
    timeout: float | None,
    memory_limit_mb: int,
    mode: Literal["thread", "turn", "call"],
    ptc_attached: bool = False,
) -> str:
    """Render the base REPL system prompt text for `CodeInterpreterMiddleware`.

    `ptc_attached` controls the "external side effects" bullet: when host
    tools are exposed as the `tools.*` namespace it points the model at the
    API reference; otherwise it states the REPL is pure computation.
    """
    if ptc_attached:
        side_effects_line = (
            "- External side effects from inside the interpreter are only "
            "reachable via the `tools.*` namespace documented in the API "
            "reference below."
        )
    else:
        side_effects_line = (
            "- The interpreter has no access to host tools, files, or the "
            "network: it is pure computation. Return values to communicate "
            "results."
        )
    if mode == "call":
        repl_intro_line = (
            f"The `{tool_name}` tool runs Python in a fresh sandboxed "
            "interpreter for each invocation."
        )
        state_persistence_line = (
            "- State (variables, functions) does not persist across tool calls. "
            "Each invocation starts from a blank environment."
        )
    elif mode == "thread":
        repl_intro_line = (
            f"The `{tool_name}` tool runs Python in a persistent sandboxed interpreter."
        )
        state_persistence_line = (
            "- State (variables, functions) persists across tool calls and across "
            "multiple turns for this conversation thread."
        )
    else:
        repl_intro_line = (
            f"The `{tool_name}` tool runs Python in a persistent sandboxed interpreter."
        )
        state_persistence_line = (
            "- State (variables, functions) persists across tool calls within "
            "a single turn of conversation. They DO NOT persist across multiple turns."
        )
    return _REPL_SYSTEM_PROMPT_TEMPLATE.format(
        repl_intro_line=repl_intro_line,
        state_persistence_line=state_persistence_line,
        side_effects_line=side_effects_line,
        timeout="unlimited" if timeout is None else timeout,
        memory_limit_mb=memory_limit_mb,
    )


def render_subagent_system_prompt(*, tool_name: str = "eval") -> str:
    """Render guidance for the top-level `task` function."""
    return _SUBAGENT_SYSTEM_PROMPT_TEMPLATE.replace("{tool_name}", tool_name)


def render_eval_tool_code_doc(*, mode: Literal["thread", "turn", "call"]) -> str:
    """Render the eval tool's `code` argument description."""
    if mode == "call":
        persistence = "Each call runs in a fresh interpreter (no cross-call state)."
    elif mode == "thread":
        persistence = (
            "State persists across calls and across turns in this conversation."
        )
    else:
        persistence = (
            "State persists across calls within a turn, but resets between turns."
        )
    return (
        "Python statement(s) to execute in the sandboxed interpreter. The value "
        f"of the final expression is returned as the result. {persistence}"
    )


def render_eval_tool_description(*, mode: Literal["thread", "turn", "call"]) -> str:
    """Render the public eval tool description."""
    if mode == "call":
        state_line = (
            "Each call runs in a fresh sandboxed interpreter with no state "
            "carried over."
        )
    elif mode == "thread":
        state_line = (
            "Persistent state is enabled: variables and functions defined in one "
            "call are visible to subsequent calls in this conversation."
        )
    else:
        state_line = (
            "Persistent state is enabled within a single turn: variables and "
            "functions defined in one call are visible to later calls within "
            "the same turn, but reset between turns."
        )
    return (
        "Execute Python in a sandboxed interpreter. "
        f"{state_line} No filesystem or network. The value of the final "
        "expression is returned as the result; `print(...)` output is captured "
        "separately."
    )


_NON_IDENTIFIER_CHARS = re.compile(r"\W")


def ptc_attribute_name(tool_name: str) -> str:
    """Return the `tools.<attr>` name under which a tool is exposed.

    Characters a Python identifier cannot hold (MCP names often use `-`) become
    `_`, a leading digit gets a `_` prefix, and a keyword gets a `_` suffix, so
    `get-issue` is `tools.get_issue` and `lambda` is `tools.lambda_`.
    """
    name = _NON_IDENTIFIER_CHARS.sub("_", tool_name) or "_"
    if name[0].isdigit():
        name = f"_{name}"
    return f"{name}_" if keyword.iskeyword(name) else name


def render_ptc_prompt(tools: Sequence[BaseTool], *, tool_name: str = "eval") -> str:
    """Build the `tools` namespace section of the system prompt."""
    if not tools:
        return ""
    blocks: list[str] = []
    for tool in tools:
        schema = _safe_json_schema(tool)
        return_type = _render_return_type(tool)
        signature = _render_signature(
            ptc_attribute_name(tool.name), schema, return_type=return_type
        )
        description = (
            (tool.description or "").strip().splitlines()[0] if tool.description else ""
        )
        prefix = f"# {description}\n" if description else ""
        blocks.append(f"{prefix}{signature}")
    body = "\n\n".join(blocks)
    return (
        "\n\n"
        "### API Reference — `tools` namespace\n\n"
        "The agent tools listed below are exposed on the `tools` object. Each "
        "takes a single dict argument (keyword arguments also work) and returns "
        "the tool's native value: strings as `str`, numbers as `int`/`float`, "
        "lists as `list`, and dicts as `dict`. You do NOT need to parse "
        "results — they are already typed.\n\n"
        "Invocation pattern: `tools.<name>({...})`.\n\n"
        f"- If the task needs multiple tool calls, prefer one `{tool_name}` "
        "invocation that performs all of them rather than splitting the work "
        f"across multiple `{tool_name}` calls — each round-trip costs a model "
        "turn.\n"
        "- Pipeline dependent calls within a single program. If a result from "
        "one tool is needed as input to a later tool, chain them in one "
        "program instead of returning the intermediate value to the model.\n"
        "- If a tool returns an ID or other value that can be passed directly "
        "into the next tool, trust it and chain the calls instead of stopping "
        "to double-check it.\n"
        "- To inspect an intermediate value, `print` it inside the same "
        "program; otherwise, fetch as much information as possible in one "
        "call.\n"
        f"- Only split work across multiple `{tool_name}` invocations when "
        "you genuinely cannot determine what to do next without additional "
        "model reasoning or user input.\n\n"
        "Example shape — substitute real tool names:\n\n"
        "```python\n"
        'users = tools.find_users({"name": "Ada"})\n'
        'user_id = users[0]["id"]\n'
        'city = tools.city_for_user({"user_id": user_id})\n'
        'normalized = tools.normalize({"name": "Ada"})\n'
        'print({"city": city, "normalized": normalized})\n'
        "```\n\n"
        "```python\n"
        f"{body}\n"
        "```"
    )


def _safe_json_schema(tool: BaseTool) -> dict[str, Any] | None:
    try:
        if tool.args_schema is None:
            return None
        model_json_schema = getattr(tool.args_schema, "model_json_schema", None)
        if callable(model_json_schema):
            return model_json_schema()
    except Exception:  # noqa: BLE001 — prompt rendering is best-effort
        return None
    return None


def _render_signature(
    fn_name: str,
    schema: dict[str, Any] | None,
    *,
    return_type: str = "Any",
) -> str:
    default_signature = f"tools.{fn_name}(input: dict[str, Any]) -> {return_type}"
    if not schema or not isinstance(schema.get("properties"), dict):
        return default_signature
    props: dict[str, Any] = schema["properties"]
    required = set(schema.get("required", []))
    fields = []
    for key, prop in props.items():
        type_str = _json_schema_to_py(prop)
        if key not in required:
            type_str = f"NotRequired[{type_str}]"
        desc = prop.get("description")
        comment = f"  # {desc}" if desc else ""
        fields.append(f'    "{key}": {type_str},{comment}')
    if not fields:
        return default_signature
    body = "\n".join(fields)
    return f"tools.{fn_name}(input: {{\n{body}\n}}) -> {return_type}"


# Return types come from the tool's underlying function annotation. We feed
# the annotation through `pydantic.TypeAdapter` to get a JSON Schema and
# render it through the same `_json_schema_to_py` we use for input args.
# Compound shapes (TypedDict, BaseModel, recursive types) end up as `$ref`
# in the schema and render as `Any`, same as nested-model input args.


def _render_return_type(tool: BaseTool) -> str:
    """Render the return annotation as a Python type, defaulting to `Any`."""
    target = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    if target is None:
        return "Any"
    annotation = inspect.Signature.empty
    with contextlib.suppress(TypeError, ValueError, NameError):
        signature = inspect.signature(target)
        resolved = get_type_hints(target)
        annotation = resolved.get("return", signature.return_annotation)
    if annotation is inspect.Signature.empty or annotation is Any:
        return "Any"
    try:
        schema = TypeAdapter(annotation).json_schema()
    except Exception:  # noqa: BLE001 — schema generation is best-effort
        return "Any"
    return _json_schema_to_py(schema)


def _json_schema_to_py(prop: dict[str, Any]) -> str:
    """Shallow JSON-Schema → Python type renderer."""
    if "enum" in prop:
        return "Literal[" + ", ".join(json.dumps(v) for v in prop["enum"]) + "]"
    if "anyOf" in prop:
        parts = [_json_schema_to_py(part) for part in prop["anyOf"]]
        return " | ".join(dict.fromkeys(parts))
    t = prop.get("type")
    if t == "string":
        return "str"
    if t == "integer":
        return "int"
    if t == "number":
        return "float"
    if t == "boolean":
        return "bool"
    if t == "null":
        return "None"
    if t == "array":
        items = prop.get("items")
        inner = _json_schema_to_py(items) if isinstance(items, dict) else "Any"
        return f"list[{inner}]"
    if t == "object":
        return "dict[str, Any]"
    return "Any"
