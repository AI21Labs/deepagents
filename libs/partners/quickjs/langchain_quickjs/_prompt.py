"""Prompt/rendering helpers for REPL and PTC system prompts."""

from __future__ import annotations

import contextlib
import inspect
import keyword
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
    "- `print(...)` output is captured and returned in a `<stdout>` block, but "
    "it is capped and truncated — return real results via the last expression, "
    "not `print`.\n"
    "- Calls are synchronous: `task(...)` and `tools.<name>(...)` return their "
    "value directly; there is no `await`.\n"
    "{side_effects_line}"
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
    description,          # full autonomous task prompt (required, positional)
    subagent_type,        # configured subagent name (required, positional)
    label=None,           # optional short UI label for this dispatch
    response_schema=None, # optional JSON Schema (dict) for structured output
)  # -> the subagent's final result
```

`task` runs a full agentic loop for the selected configured subagent and
returns its final result directly (this is a blocking, synchronous call).
`subagent_type` is required; use one of the configured subagent names.

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
a typed Python value (a `dict`) matching the schema; do not call `json.loads`
unless the subagent intentionally returned a JSON string.

#### Approval model

`task` dispatches from inside the already-running `{tool_name}` call. It does
not route through the parent agent's `ToolNode`-managed `task` tool and does not
trigger parent-level `interrupt_on` / HITL approval for each dispatch. If you
need approval before launching a subagent from the parent, use the normal
`task` tool outside `{tool_name}`, or ensure the `{tool_name}` call itself is
approval-gated.

#### Mental model

Hold your work in Python: a list of items in, a list of results out. Merge each
dispatch result back onto its item. Multi-stage analysis means: run a pass,
filter or regroup the list in Python, then run another pass over the survivors.

Dispatches run one after another (there is no in-REPL concurrency), so keep
batches sensible and let each `task` return before starting the next.

```python
files = ["/src/a.py", "/src/b.py", "/src/c.py"]  # found while exploring
reviewed = []
for file in files:
    result = task(
        f"Read {file} and review it for SQL injection. Cite line numbers.",
        "reviewer",
    )
    reviewed.append({"file": file, "result": result})
```

#### Two-stage flow with structured output

```python
tagged = []
for file in files:
    tag = task(
        f"Classify {file}: is it a request handler and is it security-risky?",
        "classifier",
        response_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "risky": {"type": "boolean"},
            },
            "required": ["kind", "risky"],
        },
    )
    tagged.append({"file": file, **tag})

risky = [it for it in tagged if it["kind"] == "handler" and it["risky"]]
deep = [
    {**it, "review": task(f"Deep security review of {it['file']}.", "reviewer")}
    for it in risky
]
```

#### Return results via the last expression, not `print`

The value of the last expression in a `{tool_name}` call is returned to you.
Make that final expression the variable holding your result. `print` is only
for incidental debugging: its output is capped and truncated, while the
returned value is not, so never `print` your actual results.

Keep large intermediate sets in Python variables and return only a compact
summary or a small slice, not the entire dataset. To persist full output, have
a subagent write it, or write it with your own file tool outside the
`{tool_name}` call.

#### Reuse what earlier calls left in scope

The interpreter is persistent within a turn: every top-level variable,
function, and class you define is kept and is available in your next
`{tool_name}` call. So if a later step needs something an earlier call produced,
**reference that variable by name** — do not write a new literal that re-types
data a previous call already returned or computed.

#### When the user asks for a "workflow"

If the user's request mentions running a "workflow", fan the work out to
subagents rather than doing it all yourself. Explore with your own tools first
as needed, then write Python in the `{tool_name}` tool that dispatches subagents
with `task(...)` and assembles their results.
"""


def render_repl_system_prompt(
    *,
    tool_name: str,
    mode: Literal["thread", "turn", "call"],
    ptc_attached: bool = False,
) -> str:
    """Render the base REPL system prompt text for `CodeInterpreterMiddleware`.

    `ptc_attached` controls the "host tools" bullet: when tools are exposed as
    the `tools.*` namespace it points the model at the API reference; otherwise
    it states the interpreter is plain computation.
    """
    if ptc_attached:
        side_effects_line = (
            "- The agent's tools are callable as the `tools.*` namespace "
            "documented in the API reference below."
        )
    else:
        side_effects_line = (
            "- No host tools are exposed. Use plain Python for computation and "
            "return values to communicate results."
        )
    if mode == "call":
        repl_intro_line = (
            f"An `{tool_name}` tool is available. It runs Python in a fresh "
            "interpreter for each invocation."
        )
        state_persistence_line = (
            "- State (variables, functions) does not persist across tool calls. "
            "Each invocation starts from a blank environment."
        )
    elif mode == "thread":
        repl_intro_line = (
            f"An `{tool_name}` tool is available. It runs Python in a persistent "
            "interpreter."
        )
        state_persistence_line = (
            "- State (variables, functions) persists across tool calls and "
            "across turns for this conversation thread."
        )
    else:
        repl_intro_line = (
            f"An `{tool_name}` tool is available. It runs Python in a persistent "
            "interpreter."
        )
        state_persistence_line = (
            "- State (variables, functions) persists across tool calls within a "
            "single turn of conversation. They DO NOT persist across turns."
        )
    return _REPL_SYSTEM_PROMPT_TEMPLATE.format(
        repl_intro_line=repl_intro_line,
        state_persistence_line=state_persistence_line,
        side_effects_line=side_effects_line,
    )


def render_subagent_system_prompt(*, tool_name: str = "eval") -> str:
    """Render guidance for the top-level `task` global."""
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
        "Python statement(s) to execute in the interpreter. The value of the "
        f"final expression is returned as the result. {persistence}"
    )


def render_eval_tool_description(*, mode: Literal["thread", "turn", "call"]) -> str:
    """Render the public eval tool description."""
    if mode == "call":
        state_line = "Each call runs in a fresh interpreter with no state carried over."
    elif mode == "thread":
        state_line = (
            "Persistent state is enabled: variables and functions defined in one "
            "call are visible to subsequent calls in this conversation."
        )
    else:
        state_line = (
            "Persistent state is enabled within a single turn: variables and "
            "functions defined in one call are visible to later calls within the "
            "same turn, but reset between turns."
        )
    return (
        "Execute Python in a persistent interpreter. "
        f"{state_line} The value of the final expression is returned as the "
        "result; `print(...)` output is captured separately."
    )


def is_valid_python_identifier(name: str) -> bool:
    """Return whether `name` is a valid, non-keyword Python identifier."""
    return name.isidentifier() and not keyword.iskeyword(name)


def is_valid_ptc_tool_name(name: str) -> bool:
    """Return whether a tool can be exposed as `tools.<name>`."""
    return is_valid_python_identifier(name)


def render_ptc_prompt(tools: Sequence[BaseTool], *, tool_name: str = "eval") -> str:
    """Build the `tools` namespace section of the system prompt."""
    if not tools:
        return ""
    blocks: list[str] = []
    for tool in tools:
        schema = _safe_json_schema(tool)
        return_type = _render_return_type(tool)
        signature = _render_signature(tool.name, schema, return_type=return_type)
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
        "takes a single dict argument (or keyword arguments) and returns the "
        "tool's native value: strings as `str`, numbers as `int`/`float`, lists "
        "as `list`, dicts as `dict`, and null as `None`. You do NOT need to "
        "parse results — they are already typed.\n\n"
        "Invocation pattern: `tools.<name>({...})`. Calls are synchronous; there "
        "is no `await`.\n\n"
        f"- If the task needs multiple tool calls, prefer one `{tool_name}` "
        "invocation that performs all of them rather than splitting the work "
        f"across multiple `{tool_name}` calls — each round-trip costs a model "
        "turn.\n"
        "- Pipeline dependent calls within a single program. If a result from "
        "one tool is needed as input to a later tool, chain them in one program "
        "instead of returning the intermediate value to the model.\n"
        "- If a tool returns an ID or other value that can be passed directly "
        "into the next tool, trust it and chain the calls.\n"
        "- To inspect an intermediate value, `print` it inside the same "
        "program; otherwise fetch as much as possible in one call.\n"
        f"- Only split work across multiple `{tool_name}` invocations when you "
        "genuinely cannot determine what to do next without more model "
        "reasoning or user input.\n\n"
        "Example shape — substitute real tool names:\n\n"
        "```python\n"
        'users = tools.find_users({"name": "Ada"})\n'
        'user_id = users[0]["id"]\n'
        'city = tools.city_for_user({"user_id": user_id})\n'
        "print(city)\n"
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
    default_signature = f"tools.{fn_name}(input: dict) -> {return_type}"
    if not schema or not isinstance(schema.get("properties"), dict):
        return default_signature
    props: dict[str, Any] = schema["properties"]
    required = set(schema.get("required", []))
    fields = []
    for key, prop in props.items():
        optional = "" if key in required else "?"
        type_str = _json_schema_to_py(prop)
        desc = prop.get("description")
        comment = f"  # {desc}" if desc else ""
        fields.append(f'    "{key}"{optional}: {type_str},{comment}')
    body = "\n".join(fields) if fields else ""
    if not body:
        return default_signature
    return f"tools.{fn_name}(input: {{\n{body}\n}}) -> {return_type}"


def _render_return_type(tool: BaseTool) -> str:
    """Render the return annotation as a Python type name, defaulting to `Any`."""
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
    with contextlib.suppress(Exception):
        schema = TypeAdapter(annotation).json_schema()
        return _json_schema_to_py(schema)
    return "Any"


def _json_schema_to_py(prop: Any) -> str:
    """Render a JSON-schema fragment as a Python type name (best-effort)."""
    if not isinstance(prop, dict):
        return "Any"
    if "anyOf" in prop and isinstance(prop["anyOf"], list):
        parts = [_json_schema_to_py(p) for p in prop["anyOf"]]
        seen: list[str] = []
        for part in parts:
            if part not in seen:
                seen.append(part)
        return " | ".join(seen) if seen else "Any"
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
        return "dict"
    return "Any"
