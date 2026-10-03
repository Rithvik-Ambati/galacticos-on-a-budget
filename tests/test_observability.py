"""observability.py: `traced_span`/`traced_node` must be a true no-op when Langfuse
isn't configured (true in every test and CI run -- no job sets LANGFUSE_* keys),
and must drive the Langfuse SDK's `start_as_current_observation` contract correctly
when it is configured. The second case is tested against a fake client since no
real Langfuse server/keys exist in this environment.
"""

from __future__ import annotations

from contextlib import contextmanager

import observability


class _FakeSpan:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.spans: list[_FakeSpan] = []  # one per call, same order as self.calls
        self.last_span: _FakeSpan | None = None
        self.scores: list[dict[str, object]] = []
        self._trace_id_counter = 0
        self._current_trace_id: str | None = None

    @contextmanager
    def start_as_current_observation(self, *, name, as_type, input, metadata):  # noqa: A002
        span = _FakeSpan()
        self.last_span = span
        self.spans.append(span)
        self.calls.append({"name": name, "as_type": as_type, "input": input, "metadata": metadata})
        self._trace_id_counter += 1
        previous = self._current_trace_id
        self._current_trace_id = f"trace-{self._trace_id_counter}"
        try:
            yield span
        finally:
            self._current_trace_id = previous

    def get_current_trace_id(self) -> str | None:
        return self._current_trace_id

    def create_score(self, *, trace_id, name, value) -> None:
        self.scores.append({"trace_id": trace_id, "name": name, "value": value})


def test_traced_span_is_a_noop_without_configured_keys(monkeypatch) -> None:
    # Explicitly forced unconfigured rather than relying on no ambient
    # LANGFUSE_* keys -- a real .env (e.g. a local docker-compose Langfuse
    # instance someone has configured for themselves) must not make this
    # test's premise false out from under it.
    monkeypatch.setattr(observability, "_client", lambda: None)
    with observability.traced_span("x") as span:
        assert span is None


def test_traced_node_decorator_is_a_noop_without_configured_keys(monkeypatch) -> None:
    monkeypatch.setattr(observability, "_client", lambda: None)

    @observability.traced_node("x")
    async def node(state: dict) -> dict:
        return {"ok": True}

    import asyncio

    assert asyncio.run(node({"session_id": "s1"})) == {"ok": True}


def test_warm_up_is_a_noop_without_configured_keys(monkeypatch) -> None:
    monkeypatch.setattr(observability, "_client", lambda: None)
    observability.warm_up()  # must not raise


def test_warm_up_calls_client_once(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(observability, "_client", lambda: calls.append(1))
    observability.warm_up()
    assert calls == [1]


def test_traced_span_drives_a_configured_client(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(observability, "_client", lambda: fake)

    with observability.traced_span("my.span", as_type="tool", input="hello", session_id="s1") as span:
        assert span is not None
        span.update(output="world")

    assert fake.calls == [{"name": "my.span", "as_type": "tool", "input": "hello", "metadata": None}]
    assert fake.last_span is not None
    assert {"session_id": "s1"} in fake.last_span.updates
    assert {"output": "world"} in fake.last_span.updates


def test_current_trace_id_is_none_without_configured_keys(monkeypatch) -> None:
    monkeypatch.setattr(observability, "_client", lambda: None)
    assert observability.current_trace_id() is None


def test_current_trace_id_returns_the_active_trace_on_a_configured_client(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(observability, "_client", lambda: fake)

    with observability.traced_span("x"):
        trace_id = observability.current_trace_id()

    assert trace_id == "trace-1"


def test_attach_score_is_a_noop_without_configured_keys(monkeypatch) -> None:
    monkeypatch.setattr(observability, "_client", lambda: None)
    observability.attach_score("trace-1", "my_metric", 0.9)  # must not raise


def test_attach_score_is_a_noop_with_no_trace_id(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(observability, "_client", lambda: fake)

    observability.attach_score(None, "my_metric", 0.9)
    assert fake.scores == []


def test_attach_score_records_against_the_given_trace(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(observability, "_client", lambda: fake)

    observability.attach_score("trace-7", "my_metric", 0.9)
    assert fake.scores == [{"trace_id": "trace-7", "name": "my_metric", "value": 0.9}]


def test_traced_node_tags_session_id_on_a_configured_client(monkeypatch) -> None:
    fake = _FakeClient()
    monkeypatch.setattr(observability, "_client", lambda: fake)

    @observability.traced_node("draw")
    async def node(state: dict) -> dict:
        return {"ok": True}

    import asyncio

    result = asyncio.run(node({"session_id": "s42"}))
    assert result == {"ok": True}
    assert fake.calls == [{"name": "node.draw", "as_type": "span", "input": None, "metadata": None}]
    assert fake.last_span is not None
    assert {"session_id": "s42"} in fake.last_span.updates
