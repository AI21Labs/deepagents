# langchain-teel

A [`deepagents`](../../deepagents) middleware that gives an agent a persistent, sandboxed **Python REPL** tool. The interpreter is CPython 3.12 compiled to WebAssembly (WASI) and run under [wasmtime](https://github.com/bytecodealliance/wasmtime-py), with [Teel](https://github.com/AI21Labs/teel) running its lookahead inside the guest.

It is the Python counterpart of [`langchain-quickjs`](../quickjs) and exposes the same `CodeInterpreterMiddleware` API. The model writes plain synchronous Python, with no `await` or `Promise.all`. Teel reads the guest's bytecode ahead of the call it is blocked on and starts the `task(...)` and `tools.<name>(...)` calls it can predict on the host, so independent calls run concurrently.

```python
from deepagents import create_deep_agent
from langchain_teel import CodeInterpreterMiddleware

agent = create_deep_agent(
    model="claude-sonnet-4-6",
    middleware=[
        CodeInterpreterMiddleware(
            python_wasm="teel/build/wasi/python.wasm", ptc=["web_search"]
        )
    ],
)
```

## Requirements

Teel's `python.wasm`: CPython 3.12 with Teel's C modules linked in and the compiled stdlib and Teel embedded via [wasi-vfs](https://github.com/kateinoigakukun/wasi-vfs). The host needs only `wasmtime`, not Teel, and works on CPython 3.11+.

```bash
cd teel
# WASI_VFS_PATH holds libwasi_vfs.a and the wasi-vfs CLI
WASI_SDK_PATH=/path/to/wasi-sdk-21 WASI_VFS_PATH=/path/to/wasi-vfs ./wasm/build.sh
# -> build/wasi/python.wasm
```

Pass its path as `CodeInterpreterMiddleware(python_wasm=...)`.

## How it works

```
host process                                   python.wasm (guest)
────────────                                   ───────────────────
eval tool ──request──▶ repl.next ◀──────────── REPL loop: exec cell
                                               task(...) / tools.x(...)
Dispatcher threads ◀──submit(real + predicted)─ teel.guest.Session
  run tools/subagents                           lookahead over the cell's bytecode
                     ──next(result)──────────▶ resumes lookahead / returns value
```

- Each conversation slot gets one `python.wasm` instance on its own thread. The guest pulls requests through the `repl.next` host function, so the host never calls into the guest.
- Host calls use Teel's three-import ABI (`submit`, `next`, `read`) and run on a host thread pool (`_protocol.Dispatcher`, which mirrors Teel's). Coroutine tools are scheduled onto the caller's event loop under `ainvoke`.
- The guest has no `zlib`, so modules that need it (`zlib`, `gzip`, and compressed `zipfile`) are unavailable.
- The compiled module is cached per process, so each additional sandbox starts in milliseconds.

## Sandbox

| Limit | Mechanism |
|---|---|
| Filesystem | Only the guest script is mounted, read-only; the stdlib is embedded in `python.wasm`. Nothing from the host is writable or listable. |
| Network, processes, threads | Not available in `wasm32-wasi`. |
| `timeout` (default 5s) | Wasmtime epoch interruption. It counts only guest computation; time blocked on `task` or `tools.*` is excluded. A timed-out interpreter is replaced, and its state is lost. |
| `memory_limit` (default 256 MiB) | Wasmtime store limits. Allocations past it raise `MemoryError` in the guest. |
| `max_ptc_calls` (default 256) | Counted in the guest for real (non-speculative) `tools.*` calls. |

## Configuration

Same as `langchain-quickjs`, except:

- `speculate` (default `True`): run predicted calls ahead of time.
- `python_wasm` (required): path to Teel's `python.wasm`.
- No snapshot options: `mode="thread"` keeps the interpreter in process memory across turns. Nothing is checkpointed, so state does not survive a restart.

## Caveats

- **Speculation runs side effects early.** A predicted call can run even though the code never reaches it, for example on a branch that is not taken. Results are also reused within an eval when the arguments match. Only expose tools that are safe to run early or skip, or set `speculate=False`.
- Arguments and results cross the sandbox boundary as JSON. Non-JSON tool results are stringified, the same way `langchain-quickjs` marshals them.
- `mode="thread"` interpreters stay alive until the middleware is closed or garbage-collected (`CodeInterpreterMiddleware.close()`).
