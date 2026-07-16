"""Thread-keyed Python REPL registry, stdout capture, and tool bridges.

Kept separate from `middleware.py` so the REPL mechanics stay testable
without constructing an agent or wiring up LangGraph state.

The REPL runs the model's code with a plain `exec` against a persistent
per-thread namespace dict. There is intentionally no sandboxing: no memory
limit, no wall-clock timeout, no restricted builtins. The only capabilities
worth wiring in are the two that let one code block orchestrate real work:

- `task(...)`      — dispatch a Deep Agents subagent (see `_subagent.py`)
- `tools.<name>()` — call the agent's own LangChain tools (PTC)

Both are exposed as ordinary *synchronous* Python callables, so the model
writes straight-line Python (loops, comprehensions, direct calls) rather than
`await`-ing anything.
"""

from __future__ import annotations

import teel
import json
import hashlib

teel.inline(json.dumps)
teel.inline(json.loads)

def _compile(code, mode):
    source = ast.unparse(code) if isinstance(code, ast.AST) else code
    h = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    filename = f"<string_{h}>"
    teel.jit(filename)
    return compile(code, filename, mode)

import ast
import contextlib
import logging
import threading
import traceback
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_quickjs._format import (
    coerce_tool_output_for_ptc,
    stringify,
)
from langchain_quickjs._subagent import (
    call_subagent_task_tool,
    find_subagent_task_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.tools import BaseTool
    from langgraph.prebuilt import ToolRuntime

logger = logging.getLogger(__name__)

_TASK_FUNCTION_NAME = "task"
_TOOLS_NAMESPACE_NAME = "tools"
_EVAL_FILENAME = "<eval>"


@dataclass
class EvalOutcome:
    """Normalized result of a single REPL eval.

    Exactly one of `result` / `error` is meaningful per call; `stdout`
    is collected from `print(...)` regardless.
    """

    stdout: str = ""
    stdout_truncated_chars: int = 0
    result: str | None = None
    error_type: str | None = None
    error_message: str = ""
    error_traceback: str | None = None


class _PTCCallBudgetExceededError(RuntimeError):
    """Raised when one eval exceeds its configured PTC call budget."""

    def __init__(self, *, limit: int, attempted: int, function_name: str) -> None:
        self.limit = limit
        self.attempted = attempted
        self.function_name = function_name
        super().__init__(self.render_message())

    def render_message(self) -> str:
        return (
            "PTC call budget exceeded "
            f"(limit={self.limit}, attempted={self.attempted}, "
            f"function={self.function_name})"
        )


@dataclass
class _PTCState:
    """Per-eval PTC state (a fresh instance is created for each eval call)."""

    remaining_calls: int | None
    outer_runtime: ToolRuntime | None = None

    def consume_call_budget(
        self, *, function_name: str, max_ptc_calls: int | None
    ) -> None:
        """Count one PTC bridge call and enforce the per-eval limit."""
        if self.remaining_calls is None:
            return
        if self.remaining_calls > 0:
            self.remaining_calls -= 1
            return
        normalized_limit = max_ptc_calls if max_ptc_calls is not None else 0
        raise _PTCCallBudgetExceededError(
            limit=normalized_limit,
            attempted=normalized_limit + 1,
            function_name=function_name,
        )


class _StdoutCapture:
    """Bounded sink for `print(...)` output during one eval.

    Accumulates written text up to `max_chars`, then counts everything past
    the cap as dropped so `format_outcome` can report the truncation. Level
    isn't tracked — the model doesn't care whether a line came from `print`
    or `sys.stdout.write`.
    """

    def __init__(self, max_chars: int) -> None:
        self._max_chars = max(0, max_chars)
        self._buf: list[str] = []
        self._len = 0
        self._dropped = 0

    def write(self, s: Any) -> int:
        if not isinstance(s, str):
            s = str(s)
        n = len(s)
        room = self._max_chars - self._len
        if room <= 0:
            self._dropped += n
            return n
        if n <= room:
            self._buf.append(s)
            self._len += n
        else:
            self._buf.append(s[:room])
            self._len = self._max_chars
            self._dropped += n - room
        return n

    def flush(self) -> None:  # pragma: no cover - satisfies the file protocol
        pass

    def drain(self) -> tuple[str, int]:
        text = "".join(self._buf)
        dropped = self._dropped
        self._buf = []
        self._len = 0
        self._dropped = 0
        return text, dropped


def _normalize_tool_input(raw: Any) -> dict[str, Any]:
    """Coerce whatever the model passed into `tools.X(...)` to a dict.

    LangChain tools accept a dict. A well-formed call passes a mapping (or
    keyword arguments, normalized to one upstream), but the model is the
    model, so guard against `None`, a bare string, or a number by wrapping
    them under a conventional `input` key — the tool's schema validation
    then produces an informative error rather than a silent miss.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    return {"input": raw}


def _synth_tool_call_id(tool_name: str) -> str:
    """Mint a synthetic tool_call_id for a PTC-driven tool invocation.

    Tools like `task` require a non-empty `tool_call_id` to stamp into their
    emitted `ToolMessage`. The real call_id lives on the outer `eval` tool
    call; we synthesise a child id so downstream state (checkpointer,
    tracing) can correlate the PTC sub-call back to the REPL cell that
    issued it.
    """
    return f"ptc_{tool_name}_{uuid.uuid4().hex[:8]}"


def _tool_uses_injected_tool_call_id(tool: Any) -> bool:
    """Return whether *tool* declares an `InjectedToolCallId` parameter.

    PTC invokes tools with an args dict via `BaseTool.run`. Tools that
    declare `InjectedToolCallId` need `tool_call_id` passed as a kwarg so
    `BaseTool._parse_input`'s built-in injection runs. Detect via the same
    combination of schema annotations and `get_type_hints` that langgraph's
    `_get_all_injected_args` uses.

    Trade-off: passing `tool_call_id` as a kwarg makes `BaseTool._format_output`
    wrap the result in a `ToolMessage` with string-coerced `.content` (unless
    the tool returns a `ToolOutputMixin` such as `Command`). For tools without
    this annotation we pass `tool_call_id=None` and recover the native return
    value.
    """
    try:
        from typing import get_type_hints  # noqa: PLC0415

        from langchain_core.tools.base import (  # noqa: PLC0415
            InjectedToolCallId,
            _is_injected_arg_type,
            get_all_basemodel_annotations,
        )
    except ImportError:  # pragma: no cover — langchain always present
        return False

    try:
        schema_annotations = get_all_basemodel_annotations(tool.get_input_schema())
    except Exception:  # noqa: BLE001 — schema introspection is best-effort
        schema_annotations = {}
    func = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    try:
        func_annotations = (
            get_type_hints(func, include_extras=True) if func is not None else {}
        )
    except Exception:  # noqa: BLE001 — type-hint resolution is best-effort
        func_annotations = {}

    # Match langgraph's merge order: schema annotations override func ones.
    all_annotations = {**func_annotations, **schema_annotations}
    return any(
        _is_injected_arg_type(type_, injected_type=InjectedToolCallId)
        for type_ in all_annotations.values()
    )


def _inject_tool_args_for_ptc(
    tool: Any,
    payload: dict[str, Any],
    outer_runtime: Any,
    tool_call_id: str,
) -> dict[str, Any]:
    """Mirror LangGraph's `ToolNode._inject_tool_args` for PTC calls.

    LangChain tools that declare `ToolRuntime` / `InjectedState` /
    `InjectedStore` only see those values when a real `ToolNode` wires them
    in. PTC calls bypass it, so we replicate the detection logic here. The
    outer runtime (captured from the active `eval` tool invocation) provides
    state/store/context/config; `tool_call_id` is freshly minted per sub-call.
    `InjectedToolCallId` is handled separately via
    `BaseTool.run(..., tool_call_id=...)` at the bridge site.
    """
    enriched = dict(payload)

    try:
        from langgraph.prebuilt.tool_node import (  # noqa: PLC0415 — optional dep, imported here so ImportError is catchable
            _get_all_injected_args,
        )
    except ImportError:  # pragma: no cover — langgraph always present
        return enriched

    injected = _get_all_injected_args(tool)
    if not injected or outer_runtime is None:
        return enriched

    # Build a ToolRuntime matching the outer one but with a fresh
    # tool_call_id. `type(outer_runtime)` rather than a literal import
    # so the shape stays in lockstep with whatever langgraph ships.
    derived = type(outer_runtime)(
        state=outer_runtime.state,
        tool_call_id=tool_call_id,
        config=outer_runtime.config,
        context=outer_runtime.context,
        store=outer_runtime.store,
        stream_writer=outer_runtime.stream_writer,
        tools=outer_runtime.tools,
        execution_info=getattr(outer_runtime, "execution_info", None),
        server_info=getattr(outer_runtime, "server_info", None),
    )
    if injected.runtime:
        enriched[injected.runtime] = derived
    # InjectedState: state can be injected under one or more arg names.
    if injected.state:
        for arg_name, state_field in injected.state.items():
            if state_field:
                enriched[arg_name] = (
                    outer_runtime.state.get(state_field)
                    if isinstance(outer_runtime.state, dict)
                    else getattr(outer_runtime.state, state_field, None)
                )
            else:
                enriched[arg_name] = outer_runtime.state
    if injected.store and outer_runtime.store is not None:
        enriched[injected.store] = outer_runtime.store
    return enriched


class _ToolsNamespace:
    """The `tools` global: attribute/item access over PTC bridge callables."""

    def __init__(self, fns: dict[str, Callable[..., Any]]) -> None:
        # Store under a mangled attribute so tool names can never shadow it.
        object.__setattr__(self, "_fns", fns)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        try:
            return self._fns[name]
        except KeyError:
            msg = f"tool {name!r} is not exposed to the REPL"
            raise AttributeError(msg) from None

    def __getitem__(self, name: str) -> Callable[..., Any]:
        return self._fns[name]

    def __contains__(self, name: str) -> bool:
        return name in self._fns

    def __dir__(self) -> list[str]:
        return sorted(self._fns)


def _split_last_expression(tree: ast.Module) -> ast.expr | None:
    """Pop a trailing bare expression off *tree*, returning it (or None).

    Emulates a REPL: the value of the final expression statement becomes the
    call's result. `tree` is mutated in place (the node is removed) so the
    caller can `exec` the remaining statements and `eval` the popped node.
    """
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        return tree.body.pop().value
    return None


class _ThreadREPL:
    """A persistent Python namespace for one LangGraph thread."""

    def __init__(
        self,
        *,
        capture_console: bool,
        max_stdout_chars: int,
        max_ptc_calls: int | None,
        subagents_enabled: bool,
    ) -> None:
        self._capture_console = capture_console
        self._max_stdout_chars = max_stdout_chars
        self._max_ptc_calls = max_ptc_calls
        self._subagents_enabled = subagents_enabled
        self._namespace: dict[str, Any] = {}
        self._ptc_tools: list[BaseTool] = []
        self._ptc_installed = False

    def install_tools(self, tools: list[BaseTool]) -> None:
        """Record the PTC toolset exposed for subsequent evals.

        The live `tools` namespace object is (re)built per eval, bound to
        that call's runtime, so this only needs to remember the toolset.
        """
        self._ptc_tools = list(tools)
        self._ptc_installed = True

    def reset(self) -> None:
        """Drop all persistent state (used for `call` persistence mode)."""
        self._namespace = {}

    def eval(  # noqa: A003 - mirrors the tool's public `eval` name
        self,
        code: str,
        *,
        outer_runtime: ToolRuntime | None = None,
    ) -> EvalOutcome:
        """Execute *code*, returning stdout, the last-expression value, or an error."""
        outcome = EvalOutcome()
        ptc_state = _PTCState(
            remaining_calls=self._max_ptc_calls,
            outer_runtime=outer_runtime,
        )
        self._bind_capabilities(outer_runtime, ptc_state)

        capture = _StdoutCapture(self._max_stdout_chars)
        redirect: contextlib.AbstractContextManager[Any] = (
            contextlib.redirect_stdout(capture)
            if self._capture_console
            else contextlib.nullcontext()
        )
        try:
            with redirect:
                self._run(code, outcome)
        finally:
            if self._capture_console:
                outcome.stdout, outcome.stdout_truncated_chars = capture.drain()
        return outcome

    def _run(self, code: str, outcome: EvalOutcome) -> None:
        try:
            tree = ast.parse(code, filename=_EVAL_FILENAME, mode="exec")
        except SyntaxError as e:
            outcome.error_type = type(e).__name__
            outcome.error_message = str(e)
            return

        result_expr = _split_last_expression(tree)
        try:
            with teel.Teel(
                max_workers=32,
                trace_path=f"/tmp/teel-trace-{uuid.uuid4().hex[:8]}.json",
            ):
                exec(  # noqa: S102 - executing model code is the whole point; no sandbox by design
                    _compile(tree, "exec"), self._namespace
                )
                if result_expr is not None:
                    value = eval(  # noqa: S307 - see above
                        _compile(ast.Expression(result_expr), "eval"),
                        self._namespace,
                    )
                    if value is not None:
                        outcome.result = stringify(value)
        except _PTCCallBudgetExceededError as e:
            outcome.error_type = "PTCCallBudgetExceeded"
            outcome.error_message = e.render_message()
        except Exception as e:  # noqa: BLE001 - surface any user-code error to the model
            outcome.error_type = type(e).__name__
            outcome.error_message = str(e)
            outcome.error_traceback = _format_user_traceback(e)

    def _bind_capabilities(
        self, runtime: ToolRuntime | None, ptc_state: _PTCState
    ) -> None:
        """Install `task` / `tools` into the namespace for this eval.

        Both are rebound every call because they close over the current
        runtime. When a capability is unavailable this turn (no PTC tools, or
        no `task` tool on the runtime), the corresponding name is removed so
        the model gets a clean `NameError` rather than a stale binding.
        """
        if self._ptc_installed:
            self._namespace[_TOOLS_NAMESPACE_NAME] = self._build_tools_namespace(
                runtime, ptc_state
            )
        else:
            self._namespace.pop(_TOOLS_NAMESPACE_NAME, None)

        task_tool = (
            find_subagent_task_tool(getattr(runtime, "tools", ()) or ())
            if self._subagents_enabled and runtime is not None
            else None
        )
        if task_tool is not None:
            self._namespace[_TASK_FUNCTION_NAME] = self._build_task_fn(
                task_tool, runtime
            )
        else:
            self._namespace.pop(_TASK_FUNCTION_NAME, None)

    def _build_tools_namespace(
        self, runtime: ToolRuntime | None, ptc_state: _PTCState
    ) -> _ToolsNamespace:
        fns: dict[str, Callable[..., Any]] = {}
        for tool in self._ptc_tools:
            fns[tool.name] = self._make_tool_bridge(tool, runtime, ptc_state)
        return _ToolsNamespace(fns)

    def _make_tool_bridge(
        self, tool: BaseTool, runtime: ToolRuntime | None, ptc_state: _PTCState
    ) -> Callable[..., Any]:
        def bridge(tool_input: Any = None, /, **kwargs: Any) -> Any:
            ptc_state.consume_call_budget(
                function_name=f"tools.{tool.name}",
                max_ptc_calls=self._max_ptc_calls,
            )
            raw = kwargs if tool_input is None and kwargs else tool_input
            payload = _normalize_tool_input(raw)
            call_id = _synth_tool_call_id(tool.name)
            args = _inject_tool_args_for_ptc(tool, payload, runtime, call_id)
            # `tool_call_id` only when the tool declares `InjectedToolCallId`;
            # passing it otherwise wraps the result in a ToolMessage and
            # string-coerces `.content`, destroying native return types.
            tool_call_id = call_id if _tool_uses_injected_tool_call_id(tool) else None
            result = tool.run(args, tool_call_id=tool_call_id)
            return coerce_tool_output_for_ptc(result)

        bridge.__name__ = bridge.__qualname__ = tool.name
        bridge.__doc__ = tool.description
        return teel.cacheable(bridge)

    def _build_task_fn(
        self, task_tool: BaseTool, runtime: ToolRuntime | None
    ) -> Callable[..., Any]:
        @teel.cacheable
        def task(
            description: str,
            subagent_type: str,
            *,
            label: str | None = None,
            response_schema: dict[str, Any] | None = None,
        ) -> Any:
            if not isinstance(description, str) or not description:
                msg = "task() requires a non-empty string `description`"
                raise ValueError(msg)
            if not isinstance(subagent_type, str) or not subagent_type:
                msg = "task() requires a non-empty string `subagent_type`"
                raise ValueError(msg)
            return call_subagent_task_tool(
                task_tool,
                description=description,
                subagent_type=subagent_type,
                response_schema=response_schema,
                runtime=runtime,
                label=label,
            )

        return task


def _format_user_traceback(exc: BaseException) -> str | None:
    """Render only the user-code frames of a traceback.

    Frames outside `<eval>` (this module's `exec`/`eval` machinery, tool
    internals) are dropped so the model sees line numbers in its own code and
    no host filesystem paths leak into the tool output.
    """
    frames = [
        frame
        for frame in traceback.extract_tb(exc.__traceback__)
        if frame.filename == _EVAL_FILENAME
    ]
    if not frames:
        return None
    return "".join(traceback.format_list(frames)).rstrip() or None


class _Registry:
    """Thread-keyed store of `_ThreadREPL` slots.

    One slot per LangGraph `thread_id` so persistent globals from one
    conversation cannot leak into another. Slots live in-memory for the
    lifetime of the process (or until evicted); nothing is checkpointed.
    """

    def __init__(
        self,
        *,
        capture_console: bool,
        max_stdout_chars: int,
        max_ptc_calls: int | None,
        subagents_enabled: bool,
    ) -> None:
        self._capture_console = capture_console
        self._max_stdout_chars = max_stdout_chars
        self._max_ptc_calls = max_ptc_calls
        self._subagents_enabled = subagents_enabled
        self._slots: dict[str, _ThreadREPL] = {}
        self._lock = threading.Lock()

    def get(self, thread_id: str) -> _ThreadREPL:
        with self._lock:
            repl = self._slots.get(thread_id)
            if repl is None:
                repl = self._build_repl()
                self._slots[thread_id] = repl
            return repl

    def get_if_exists(self, thread_id: str) -> _ThreadREPL | None:
        with self._lock:
            return self._slots.get(thread_id)

    def evict(self, thread_id: str) -> None:
        with self._lock:
            self._slots.pop(thread_id, None)

    def reset_repl(self, thread_id: str) -> None:
        with self._lock:
            repl = self._slots.get(thread_id)
        if repl is not None:
            repl.reset()

    def close(self) -> None:
        with self._lock:
            self._slots.clear()

    def _build_repl(self) -> _ThreadREPL:
        return _ThreadREPL(
            capture_console=self._capture_console,
            max_stdout_chars=self._max_stdout_chars,
            max_ptc_calls=self._max_ptc_calls,
            subagents_enabled=self._subagents_enabled,
        )
