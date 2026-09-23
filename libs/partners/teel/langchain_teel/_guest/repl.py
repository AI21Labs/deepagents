"""Guest REPL loop: runs inside python.wasm, driven by the host.

The host never calls into the guest. The guest pulls work from the host with
the `repl.next` host function, which carries the previous cell's outcome and
returns the next request. `task(...)` and `tools.<name>(...)` are teel host
functions, so the lookahead can dispatch predicted calls to the host while a
real call is still running.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import linecache
import reprlib
import traceback
from typing import Any

# From the WASI build's site-packages, not the host.
from teel import lookahead
from teel.guest import HostError, Session, host_function

_CELL_PREFIX = "<eval-"

# `repr` of a compound result can be huge; bound it before the host truncates.
_repr = reprlib.Repr()
_repr.maxstring = 4_000
_repr.maxother = 4_000
_repr.maxlist = _repr.maxdict = _repr.maxtuple = _repr.maxset = 100
_repr.maxlevel = 6


@host_function(name="repl.next")
def _next_request(outcome: dict[str, Any] | None) -> dict[str, Any]: ...


@host_function(name="task")
def _task(
    description: str,
    subagent_type: str,
    *,
    label: str | None = None,
    response_schema: dict[str, Any] | None = None,
) -> Any: ...


class PTCCallBudgetExceededError(RuntimeError):
    """Raised when one cell makes more `tools.*` calls than allowed."""

    def __init__(self, *, limit: int, function_name: str) -> None:
        """Describe the call that went over `limit`."""
        super().__init__(
            f"PTC call budget exceeded (limit={limit}, attempted={limit + 1}, "
            f"function={function_name})"
        )


class _Tools:
    """The `tools` global: one attribute per exposed host tool."""

    def __init__(self, functions: dict[str, Any]) -> None:
        self.__dict__.update(functions)

    def __repr__(self) -> str:
        return f"<tools: {', '.join(sorted(self.__dict__))}>"


class _CellSession(Session):
    """A teel session that also enforces the per-cell `tools.*` budget.

    Only real calls reach `call`; speculative ones go straight to the host.
    """

    def __init__(self, max_ptc_calls: int | None) -> None:
        super().__init__()
        self._limit = max_ptc_calls
        self._used = 0

    def call(self, name: str, args: tuple, kwargs: dict[str, Any]) -> Any:
        if self._limit is not None and name.startswith("tools."):
            if self._used >= self._limit:
                raise PTCCallBudgetExceededError(limit=self._limit, function_name=name)
            self._used += 1
        return super().call(name, args, kwargs)


class _Capture:
    """Bounded text sink for `print` output during one cell."""

    def __init__(self, max_chars: int) -> None:
        self._max_chars = max(0, max_chars)
        self._parts: list[str] = []
        self._size = 0
        self.dropped = 0

    def write(self, text: str) -> int:
        room = self._max_chars - self._size
        kept = text[: max(0, room)]
        if kept:
            self._parts.append(kept)
            self._size += len(kept)
        self.dropped += len(text) - len(kept)
        return len(text)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return "".join(self._parts)


_tool_functions: dict[str, Any] = {}


def _tool_function(name: str) -> Any:
    """Return the (cached) host function for `tools.<name>`.

    Cached so each name registers one lookahead target for the process.
    """
    function = _tool_functions.get(name)
    if function is None:

        def stub(tool_input: Any = None, /, **kwargs: Any) -> Any: ...

        stub.__name__ = stub.__qualname__ = name
        function = _tool_functions[name] = host_function(stub, name=f"tools.{name}")
    return function


def _bind_capabilities(namespace: dict[str, Any], request: dict[str, Any]) -> None:
    if request["task"]:
        namespace["task"] = _task
    else:
        namespace.pop("task", None)
    if request["tools"] is None:
        namespace.pop("tools", None)
    else:
        namespace["tools"] = _Tools({n: _tool_function(n) for n in request["tools"]})


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return _repr.repr(value)
    except Exception:
        return object.__repr__(value)


def _user_traceback(exc: BaseException) -> str | None:
    """Keep only frames from model cells, so no guest internals leak."""
    frames = [
        frame
        for frame in traceback.extract_tb(exc.__traceback__)
        if frame.filename.startswith(_CELL_PREFIX)
    ]
    return "".join(traceback.format_list(frames)).rstrip() or None


def _compile_cell(code: str, filename: str) -> tuple[Any, Any]:
    """Split the cell into its statements and a trailing expression, if any."""
    tree = ast.parse(code, filename=filename, mode="exec")
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    body = compile(tree, filename, "exec")
    return body, compile(last, filename, "eval") if last is not None else None


def _execute(code: str, filename: str, namespace: dict[str, Any]) -> Any:
    body, last = _compile_cell(code, filename)
    exec(body, namespace)
    return eval(last, namespace) if last is not None else None


def _run_cell(
    request: dict[str, Any], namespace: dict[str, Any], cell: int
) -> dict[str, Any]:
    code = request["code"]
    filename = f"{_CELL_PREFIX}{cell}>"
    linecache.cache[filename] = (
        len(code),
        None,
        code.splitlines(keepends=True),
        filename,
    )
    if request["speculate"]:
        lookahead.add_source(filename)
    _bind_capabilities(namespace, request)

    outcome: dict[str, Any] = {"result": None, "error_type": None}
    capture = _Capture(request["max_stdout_chars"])
    try:
        with (
            _CellSession(request["max_ptc_calls"]),
            contextlib.redirect_stdout(capture),
            contextlib.redirect_stderr(capture),
        ):
            value = _execute(code, filename, namespace)
        if value is not None:
            outcome["result"] = _stringify(value)
    except PTCCallBudgetExceededError as exc:
        outcome.update(error_type="PTCCallBudgetExceeded", error_message=str(exc))
    except HostError as exc:
        outcome.update(
            error_type=exc.type_name,
            error_message=exc.message,
            error_traceback=_user_traceback(exc),
        )
    except (Exception, SystemExit) as exc:
        outcome.update(
            error_type=type(exc).__name__,
            error_message=str(exc),
            error_traceback=_user_traceback(exc),
        )
    outcome.update(stdout=capture.getvalue(), stdout_truncated_chars=capture.dropped)
    return outcome


def _fresh_namespace() -> dict[str, Any]:
    return {"__name__": "__main__", "__builtins__": builtins}


def main() -> None:
    """Serve requests from the host until it asks the guest to exit."""
    namespace = _fresh_namespace()
    outcome = None
    cell = 0
    while True:
        request = _next_request(outcome)
        if request.get("exit"):
            return
        if request.get("reset"):
            namespace = _fresh_namespace()
            outcome = {"result": None, "error_type": None}
            continue
        cell += 1
        outcome = _run_cell(request, namespace, cell)


if __name__ == "__main__":
    main()
