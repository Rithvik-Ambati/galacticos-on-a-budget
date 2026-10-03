"""Langfuse tracing, the project's one observability integration (docs/DESIGN.md
section 14). A single thin wrapper so every instrumented call site
(llm/provider.py, llm/narrator.py, rag/retriever.py, rag/rerank.py,
llm/sql_tool.py, graph/nodes.py) shares one on/off switch and one failure mode.

Deliberately a standalone module (not inside engine/, llm/, or rag/): CLAUDE.md's
module boundaries say engine/ must not import llm/, api/, or db/, and this needs
to be importable from engine-adjacent code (graph/nodes.py wraps engine calls)
as well as rag/ and llm/ -- a leaf utility like config/, with no dependency on
any of them.

If `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` aren't set (true for every CI job
and anyone who hasn't opted in locally -- this project has no deployment to put
real keys into), `traced_span` is a no-op: it yields `None` and does no network
call, so nothing here can make a job need a secret or fail when Langfuse is
unreachable.

Session tagging: Langfuse's OTEL-based SDK propagates `session_id` set on a trace's
root span to every span nested under it automatically -- `graph/nodes.py` sets it
once per node invocation (covering "engine analyse/counter/simulate spans tagged
with session_id" directly, since those are node functions), and any `traced_span`
opened underneath (an LLM generation, a retrieval, a rerank, a SQL tool call) is
part of the same trace without repeating the session_id on every leaf.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, TypeVar

from config.settings import get_settings

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


@lru_cache
def _client() -> Any | None:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    from langfuse import get_client

    return get_client()


@contextmanager
def traced_span(
    name: str,
    *,
    as_type: str = "span",
    input: Any = None,  # noqa: A002 - matches the Langfuse SDK's own kwarg name
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Wraps a block of code in a Langfuse observation when tracing is configured;
    a no-op context yielding `None` otherwise. Callers that want to record an
    output or extra fields must guard with `if span is not None: span.update(...)`
    since there's nothing to update when tracing is off."""
    client = _client()
    if client is None:
        yield None
        return

    with client.start_as_current_observation(name=name, as_type=as_type, input=input, metadata=metadata) as span:
        if session_id is not None:
            span.update(session_id=session_id)
        yield span


def current_trace_id() -> str | None:
    """The active trace's id, for attaching an eval score after the fact
    (`attach_score`) -- only meaningful while inside a `traced_span` context.
    `None` when tracing isn't configured or nothing is currently open."""
    client = _client()
    if client is None:
        return None
    return client.get_current_trace_id()  # type: ignore[no-any-return]


def attach_score(trace_id: str | None, name: str, value: float) -> None:
    """evals/numeric_eval.py and evals/faithfulness_eval.py call this after
    scoring a sample, to record that score against the trace the sample's LLM
    calls were made in (`evals/_report_samples.py` captures `trace_id` via
    `current_trace_id()` while narrating each sample). A no-op if tracing isn't
    configured or the sample never got a trace_id (e.g. tracing was off when the
    sample itself was generated)."""
    client = _client()
    if client is None or trace_id is None:
        return
    client.create_score(trace_id=trace_id, name=name, value=value)


def traced_node(name: str) -> Callable[[_F], _F]:
    """Decorator for an async `GameState -> dict` node function
    (`graph/nodes.py`): wraps the whole call in a `traced_span` tagged with
    `state["session_id"]`, with zero re-indentation of the node's own body.
    Covers "engine analyse/counter/simulate spans tagged with session_id"
    directly, since those are node functions; every other node gets the same
    coverage as a side effect."""

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        async def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            with traced_span(f"node.{name}", session_id=state.get("session_id")):
                return await func(state, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
