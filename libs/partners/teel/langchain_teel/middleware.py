"""`CodeInterpreterMiddleware`: exposes a sandboxed Python REPL tool."""

import asyncio
import contextlib
import functools
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ModelRequest,
    ModelResponse,
    PrivateStateAttr,
    ResponseT,
    TracePolicy,
    omit_payload,
)
from langchain.tools import BaseTool, ToolRuntime
from langchain_core._api import beta
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

from langchain_teel._format import format_outcome
from langchain_teel._prompt import (
    render_eval_tool_code_doc,
    render_eval_tool_description,
    render_repl_system_prompt,
    render_subagent_system_prompt,
)
from langchain_teel._ptc import (
    PTCOption,
    filter_tools_for_ptc,
    render_ptc_prompt,
)
from langchain_teel._repl import EvalOutcome, _Registry
from langchain_teel._sandbox import check_python_wasm
from langchain_teel._subagent import find_subagent_task_tool

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_LIMIT = 256 * 1024 * 1024
_DEFAULT_TIMEOUT = 5.0
_DEFAULT_MAX_PTC_CALLS = 256
_DEFAULT_MAX_RESULT_CHARS = 4_000
_DEFAULT_TOOL_NAME = "eval"

PersistenceMode = Literal["thread", "turn", "call"]


class REPLState(AgentState):
    """State schema for `CodeInterpreterMiddleware`."""

    _teel_slot_id: NotRequired[Annotated[str, PrivateStateAttr]]


class EvalSchema(BaseModel):
    """Input schema for the `eval` tool."""

    code: str = Field(
        description=(
            "Python statement(s) to execute. The value of the final expression "
            "is returned as the result. No filesystem or network access."
        ),
    )


def _resolve_mode(*, mode: str | None) -> PersistenceMode:
    """Normalize persistence mode and enforce invariant constraints."""
    match mode:
        case None | "thread":
            return "thread"
        case "turn":
            return "turn"
        case "call":
            return "call"
        case _:
            msg = "`mode` must be one of 'thread', 'turn', or 'call'."
            raise ValueError(msg)


def _new_slot_id() -> str:
    """Create a private interpreter slot id."""
    return f"teel_{uuid.uuid4().hex}"


@beta()
class CodeInterpreterMiddleware(AgentMiddleware[REPLState, ContextT, ResponseT]):
    """Middleware exposing a sandboxed Python REPL to the agent.

    The REPL is CPython 3.12 compiled to WebAssembly (WASI) and run under
    wasmtime, so model code has no filesystem, network, or process access.
    Each conversation gets its own interpreter instance.

    `task(...)` and `tools.<name>(...)` are host functions: the guest
    blocks on them like ordinary calls, while teel's lookahead predicts
    upcoming calls from the guest's bytecode and starts them on the host
    ahead of time. Plain sequential code therefore runs independent tool
    calls and subagents concurrently.

    Requires teel's `python.wasm`, built by teel's `wasm/build.sh` with the
    stdlib embedded.

    Args:
        python_wasm: Path to teel's `python.wasm`.
        memory_limit: Bytes of linear memory the interpreter may use.
            Allocations past it raise `MemoryError` in the guest.
            Default 256 MiB.
        timeout: Seconds of guest computation allowed per `eval`, or `None`
            for no limit. Time the guest spends blocked on `task` or
            `tools.*` does not count. A timed-out interpreter is discarded
            and replaced, so its state is lost. Default 5.
        max_ptc_calls: Maximum number of real `tools.*` calls allowed during
            one `eval`. Exceeding it raises in the guest before the call
            reaches the host; uncaught overflows surface as
            `PTCCallBudgetExceeded`. `None` disables the budget. Default 256.

            !!! warning

                Setting `max_ptc_calls=None` can allow unbounded host-call
                loops (DoS risk). Only disable in trusted environments.
        tool_name: Name of the tool exposed to the model. Default `eval`.
        max_result_chars: Result and stdout blocks are independently
            truncated to this many characters before being sent back to
            the model. Default 4000.
        capture_console: If `True`, capture `print(...)` / stdout / stderr
            output and emit it in a `<stdout>` block alongside the result.
            Default `True`.
        subagents: If `True`, expose the top-level `task(...)` function when
            the current agent has a Deep Agents `task` tool.

            !!! warning

                `task(...)` calls run inside an already-approved `eval`
                invocation and do not trigger parent-level `interrupt_on` /
                HITL approval per dispatch.
        ptc: Programmatic tool calling — expose agent tools inside the REPL
            as `tools.<name>(input)`. A list of tool names (matched against
            the agent's toolset) and/or `BaseTool` instances. `None`
            disables PTC. The REPL's own tool is always excluded.

            !!! warning

                PTC calls do **not** go through the normal `ToolNode` path,
                so `interrupt_on` / HITL approval is not enforced per call.
        mode: REPL state persistence mode.

            - `"thread"`: state persists across calls and across turns while
              this process lives. It is not checkpointed.
            - `"turn"`: state persists across calls within a turn only.
            - `"call"`: each eval call runs with fresh globals.

            Defaults to `"thread"`.
        speculate: If `True`, predict and start `task` / `tools.*` calls
            before the guest reaches them.

            !!! warning

                Speculation may run a call the code never makes, for example
                one on a branch that is not taken, and results are shared
                within an `eval` by arguments. Only expose tools whose calls
                are safe to repeat or skip, or set `speculate=False`.

    Example:
        ```python
        from deepagents import create_deep_agent
        from langchain_teel import CodeInterpreterMiddleware

        agent = create_deep_agent(
            model="claude-sonnet-4-6",
            middleware=[
                CodeInterpreterMiddleware(python_wasm="teel/build/wasi/python.wasm")
            ],
        )
        ```
    """

    trace_policy = TracePolicy(process_inputs=omit_payload)

    state_schema = REPLState

    def __init__(
        self,
        *,
        python_wasm: str | os.PathLike[str],
        memory_limit: int = _DEFAULT_MEMORY_LIMIT,
        timeout: float | None = _DEFAULT_TIMEOUT,
        max_ptc_calls: int | None = _DEFAULT_MAX_PTC_CALLS,
        tool_name: str = _DEFAULT_TOOL_NAME,
        max_result_chars: int = _DEFAULT_MAX_RESULT_CHARS,
        capture_console: bool = True,
        subagents: bool = True,
        ptc: PTCOption | None = None,
        mode: PersistenceMode | None = None,
        speculate: bool = True,
    ) -> None:
        """Initialize REPL middleware state and build the exposed eval tool."""
        super().__init__()
        if max_ptc_calls is not None and max_ptc_calls < 1:
            msg = "`max_ptc_calls` must be >= 1 or None"
            raise ValueError(msg)
        self._memory_limit_mb = memory_limit // (1024 * 1024)
        self._timeout = timeout
        self._tool_name = tool_name
        self._max_result_chars = max_result_chars
        self._subagents = subagents
        self._ptc = ptc
        self._mode = _resolve_mode(mode=mode)
        self._registry = _Registry(
            check_python_wasm(python_wasm),
            memory_limit=memory_limit,
            timeout=timeout,
            capture_console=capture_console,
            max_stdout_chars=max_result_chars,
            max_ptc_calls=max_ptc_calls,
            subagents_enabled=subagents,
            speculate=speculate,
        )
        self._base_prompt_cache: dict[bool, str] = {}
        self._ptc_prompt_cache: tuple[frozenset[str], str] | None = None
        self.tools: list[BaseTool] = [self._build_tool()]

    def _build_tool(self) -> BaseTool:
        tool_name = self._tool_name
        max_chars = self._max_result_chars
        middleware = self
        code_doc = render_eval_tool_code_doc(mode=self._mode)
        tool_description = render_eval_tool_description(mode=self._mode)

        def _make_tool_message(
            outcome: EvalOutcome, tool_call_id: str | None
        ) -> ToolMessage:
            return ToolMessage(
                content=format_outcome(outcome, max_result_chars=max_chars),
                tool_call_id=tool_call_id,
                name=tool_name,
            )

        def sync_eval(
            runtime: ToolRuntime[None, Any],
            code: Annotated[str, code_doc],
        ) -> ToolMessage:
            slot_id = middleware._slot_id(runtime.state)
            repl = middleware._registry.get(slot_id)
            try:
                outcome = repl.eval(code, outer_runtime=runtime)
            finally:
                if middleware._mode == "call":
                    middleware._registry.reset_repl(slot_id)
            return _make_tool_message(outcome, runtime.tool_call_id)

        async def async_eval(
            runtime: ToolRuntime[None, Any],
            code: Annotated[str, code_doc],
        ) -> ToolMessage:
            slot_id = middleware._slot_id(runtime.state)
            repl = middleware._registry.get(slot_id)
            try:
                # The guest blocks its thread; host calls come back onto this
                # loop through `outer_loop`.
                outcome = await asyncio.to_thread(
                    functools.partial(
                        repl.eval,
                        code,
                        outer_runtime=runtime,
                        outer_loop=asyncio.get_running_loop(),
                    )
                )
            finally:
                if middleware._mode == "call":
                    await asyncio.to_thread(middleware._registry.reset_repl, slot_id)
            return _make_tool_message(outcome, runtime.tool_call_id)

        return StructuredTool.from_function(
            name=tool_name,
            description=tool_description,
            func=sync_eval,
            coroutine=async_eval,
            infer_schema=False,
            args_schema=EvalSchema,
            metadata={"ls_code_input_language": "python"},
        )

    def _slot_id(self, state: Mapping[str, object]) -> str:
        """Return the private interpreter slot initialized by `before_agent`."""
        slot_id = state.get("_teel_slot_id")
        if isinstance(slot_id, str) and slot_id:
            return slot_id
        msg = (
            "Teel private state is missing `_teel_slot_id`; "
            "`CodeInterpreterMiddleware.before_agent` must run before eval."
        )
        raise ValueError(msg)

    def before_agent(
        self,
        state: REPLState,
        runtime: "Runtime[ContextT]",  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Ensure a private REPL slot id exists in state."""
        slot_id = state.get("_teel_slot_id")
        if isinstance(slot_id, str) and slot_id:
            return None
        return {"_teel_slot_id": _new_slot_id()}

    async def abefore_agent(
        self,
        state: REPLState,
        runtime: "Runtime[ContextT]",
    ) -> dict[str, Any] | None:
        """Async variant of `before_agent`."""
        return self.before_agent(state, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT]:
        """Inject the REPL's system-prompt snippet on every model call."""
        prompt = self._prepare_for_call(request)
        return handler(
            request.override(
                system_message=self._extend(request.system_message, prompt)
            ),
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[
            [ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]
        ],
    ) -> ModelResponse[ResponseT]:
        """(async) Inject the REPL's system-prompt snippet on every model call."""
        prompt = self._prepare_for_call(request)
        return await handler(
            request.override(
                system_message=self._extend(request.system_message, prompt)
            ),
        )

    def _base_prompt(self, *, ptc_attached: bool) -> str:
        """Return the base REPL system prompt, rendered lazily and memoized."""
        cached = self._base_prompt_cache.get(ptc_attached)
        if cached is None:
            cached = render_repl_system_prompt(
                tool_name=self._tool_name,
                timeout=self._timeout,
                memory_limit_mb=self._memory_limit_mb,
                mode=self._mode,
                ptc_attached=ptc_attached,
            )
            self._base_prompt_cache[ptc_attached] = cached
        return cached

    def _prepare_for_call(self, request: ModelRequest[ContextT]) -> str:
        """Install PTC bindings for this turn and return the prompt addendum.

        Reads the live tool list off the request (middlewares upstream may
        have filtered it), installs PTC bridges on the current slot's REPL,
        and renders matching API-reference text.
        """
        request_tools: list[BaseTool] = list(getattr(request, "tools", []) or [])

        subagent_section = ""
        if self._subagents and find_subagent_task_tool(request_tools) is not None:
            subagent_section = render_subagent_system_prompt(tool_name=self._tool_name)

        if self._ptc is None:
            return self._base_prompt(ptc_attached=False) + subagent_section

        exposed = filter_tools_for_ptc(
            request_tools,
            self._ptc,
            self_tool_name=self._tool_name,
        )
        prompt = self._base_prompt(ptc_attached=bool(exposed)) + subagent_section
        slot_id = self._slot_id(getattr(request, "state", {}))
        self._registry.get(slot_id).install_tools(exposed)
        # Cache by the set of exposed names. The set doesn't encode tool
        # *identity* — if a tool keeps its name but its schema changes
        # between turns, the cached prompt staleness is on the caller.
        exposed_names = frozenset(t.name for t in exposed)
        if self._ptc_prompt_cache is None or self._ptc_prompt_cache[0] != exposed_names:
            self._ptc_prompt_cache = (
                exposed_names,
                render_ptc_prompt(exposed, tool_name=self._tool_name),
            )
        return prompt + self._ptc_prompt_cache[1]

    def _extend(
        self, system_message: SystemMessage | None, prompt: str
    ) -> SystemMessage:
        return append_to_system_message(system_message, prompt)

    def after_agent(
        self,
        state: REPLState,
        runtime: "Runtime[ContextT]",  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Evict this turn's REPL unless state persists across turns."""
        if self._mode != "thread":
            self._registry.evict(self._slot_id(state))
        return None

    async def aafter_agent(
        self,
        state: REPLState,
        runtime: "Runtime[ContextT]",
    ) -> dict[str, Any] | None:
        """Async variant of `after_agent`."""
        return await asyncio.to_thread(self.after_agent, state, runtime)

    def close(self) -> None:
        """Stop every interpreter this middleware started."""
        self._registry.close()

    def __del__(self) -> None:
        """Best-effort sandbox cleanup on GC; never raises at shutdown."""
        # `__del__` must not raise during interpreter shutdown, when
        # dependencies may already be half-unloaded.
        with contextlib.suppress(Exception):
            self._registry.close()
