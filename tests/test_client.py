"""Offline tests for the Mnemo client, using httpx's MockTransport.

They pin the wire contract: request bodies must contain ONLY the keys the API
accepts (the server's global validation rejects unknown keys with a 400), and
responses parse into the typed models.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from getmnemo import AsyncMnemo, Mnemo, MnemoHTTPError

ISO = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc).isoformat()

# Keys the API accepts on each body. Anything else trips the global
# ValidationPipe with a 400 — the tests below assert we never send more.
ALLOWED_ADD_KEYS = {"scope", "containerTag", "containerType", "metadata", "source", "items"}
ALLOWED_ITEM_KEYS = {
    "id",
    "content",
    "idempotencyKey",
    "memoryType",
    "polarity",
    "dueAt",
    "mutationPolicy",
    "metadata",
    "source",
}
ALLOWED_SEARCH_KEYS = {
    "scope",
    "containerTag",
    "q",
    "scopes",
    "containerTags",
    "searchMode",
    "limit",
    "filters",
    "includeSources",
    "polarity",
    "intentOverride",
    "agentic",
    "mode",
}


def _memory_record(memory_id: str = "11111111-1111-4111-8111-111111111111") -> dict[str, Any]:
    return {
        "id": memory_id,
        "scopeKey": "user:jane",
        "content": "User prefers Japanese rice.",
        "memoryType": "preference",
        "metadata": {"source": "test"},
        "createdAt": ISO,
        "updatedAt": ISO,
    }


def _add_response() -> dict[str, Any]:
    return {
        "scopeKey": "user:jane",
        "scope": {"type": "user", "id": "jane"},
        "items": [_memory_record()],
        "stats": {"total": 1, "created": 1, "deduplicated": 0},
        "receipt": {
            "writeId": "22222222-2222-4222-8222-222222222222",
            "status": "searchable",
            "searchableAt": ISO,
            "items": [
                {
                    "inputIndex": 0,
                    "memoryId": "11111111-1111-4111-8111-111111111111",
                    "status": "created",
                    "searchStatus": "searchable",
                }
            ],
        },
    }


def _search_response() -> dict[str, Any]:
    return {
        "results": [
            {
                "resultType": "memory",
                "score": 0.91,
                "scopeKey": "user:jane",
                "content": "User prefers Japanese rice.",
                "metadata": {"source": "test"},
                "createdAt": ISO,
                "updatedAt": ISO,
                "memoryId": "11111111-1111-4111-8111-111111111111",
                "memoryType": "preference",
                "polarity": "positive",
            }
        ],
        "positivePreferences": [],
        "hardConstraints": [],
        "searchMode": "hybrid",
        "queryIntent": "simple_recall",
        "queryIntentConfidence": 1,
        "abstained": False,
        "reranked": False,
        "rawBestVectorSim": 0.7,
        "latency": {
            "parallelMs": 1,
            "strategyMs": 1,
            "fusionMs": 0,
            "rerankerMs": 0,
            "totalMs": 2,
        },
    }


def _sync(handler) -> Mnemo:  # type: ignore[no-untyped-def]
    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return Mnemo(api_key="test", default_container_tag="user:jane", client=client)


# ----- add -----


def test_add_sends_container_and_items_only() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/v1/memories"
        body = json.loads(req.content)
        assert set(body) <= ALLOWED_ADD_KEYS, f"unknown body keys: {set(body) - ALLOWED_ADD_KEYS}"
        assert body["containerTag"] == "user:jane"
        assert isinstance(body["items"], list) and len(body["items"]) == 1
        item = body["items"][0]
        assert set(item) <= ALLOWED_ITEM_KEYS, f"unknown item keys: {set(item) - ALLOWED_ITEM_KEYS}"
        assert item == {
            "content": "User prefers Japanese rice.",
            "metadata": {"source": "test"},
        }
        return httpx.Response(201, json=_add_response())

    res = _sync(handler).add("User prefers Japanese rice.", metadata={"source": "test"})
    assert res.scope_key == "user:jane"
    assert res.items[0].id == "11111111-1111-4111-8111-111111111111"
    assert res.stats is not None and res.stats.created == 1
    assert res.receipt is not None and res.receipt.items[0].status == "created"


def test_add_per_call_container_overrides_default() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["containerTag"] == "project:alpha"
        return httpx.Response(201, json=_add_response())

    _sync(handler).add("note", container_tag="project:alpha")


def test_add_many_builds_items_and_rejects_unknown_keys() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert set(body) == {"containerTag", "items"}
        assert body["items"] == [
            {"content": "a"},
            {"content": "b", "idempotencyKey": "k-1", "memoryType": "fact"},
        ]
        return httpx.Response(201, json=_add_response())

    client = _sync(handler)
    client.add_many(["a", {"content": "b", "idempotency_key": "k-1", "memory_type": "fact"}])

    with pytest.raises(ValueError, match="unknown key"):
        client.add_many([{"content": "x", "actor_id": "nope"}])
    with pytest.raises(ValueError, match="between 1 and 100"):
        client.add_many([])
    with pytest.raises(ValueError, match="between 1 and 100"):
        client.add_many(["x"] * 101)
    with pytest.raises(ValueError, match="content"):
        client.add_many([{"metadata": {}}])


def test_container_required_when_no_default() -> None:
    client = Mnemo(
        api_key="test",
        client=httpx.Client(
            base_url="http://test",
            transport=httpx.MockTransport(lambda _r: httpx.Response(201, json=_add_response())),
        ),
    )
    with pytest.raises(ValueError, match=r"<type>:<id>"):
        client.add("orphan content")
    with pytest.raises(ValueError, match=r"<type>:<id>"):
        client.search("anything")


def test_container_tag_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GETMNEMO_CONTAINER_TAG", "user:envjane")

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["containerTag"] == "user:envjane"
        return httpx.Response(201, json=_add_response())

    client = Mnemo(
        api_key="test",
        client=httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)),
    )
    client.add("env container")


# ----- search -----


def test_search_sends_q_and_container_only() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/search"
        body = json.loads(req.content)
        assert set(body) <= ALLOWED_SEARCH_KEYS, (
            f"unknown body keys: {set(body) - ALLOWED_SEARCH_KEYS}"
        )
        assert body == {"q": "rice", "containerTag": "user:jane"}
        return httpx.Response(201, json=_search_response())

    results = _sync(handler).search("rice")
    assert len(results) == 1
    hit = results[0]
    assert hit.result_type == "memory"
    assert hit.score == 0.91
    assert hit.memory_id == "11111111-1111-4111-8111-111111111111"
    assert hit.content == "User prefers Japanese rice."
    assert hit.polarity == "positive"


def test_search_sends_limit_when_given() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body == {"q": "rice", "containerTag": "user:jane", "limit": 5}
        return httpx.Response(201, json=_search_response())

    _sync(handler).search("rice", limit=5)


def test_search_container_not_found_returns_empty() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Container not found", "statusCode": 404})

    assert _sync(handler).search("anything") == []


def test_search_tolerates_future_empty_results_shape() -> None:
    # The in-flight API change returns 200 + empty results instead of 404.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "abstained": True})

    assert _sync(handler).search("anything") == []


# ----- errors + workspace header -----


def test_http_error_includes_status_and_body() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid api key"})

    with pytest.raises(MnemoHTTPError) as ei:
        _sync(handler).search("anything")
    assert ei.value.status == 401
    assert "invalid api key" in str(ei.value)


def test_add_404_still_raises() -> None:
    # Only search() swallows 404s; writes must surface them.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    with pytest.raises(MnemoHTTPError) as ei:
        _sync(handler).add("content")
    assert ei.value.status == 404


def test_workspace_header_only_sent_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GETMNEMO_WORKSPACE_ID", raising=False)
    without = Mnemo(api_key="test", default_container_tag="user:jane")
    assert "x-workspace-id" not in without._client.headers
    without.close()

    with_ws = Mnemo(api_key="test", default_container_tag="user:jane", workspace_id="ws_1")
    assert with_ws._client.headers["x-workspace-id"] == "ws_1"
    with_ws.close()


# ----- update / delete / list -----


def test_update_threads_container_and_requires_a_field() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH"
        assert req.url.params["containerTag"] == "user:jane"
        body = json.loads(req.content)
        assert body == {"content": "updated"}
        return httpx.Response(200, json=_memory_record())

    client = _sync(handler)
    mem = client.update("mem_1", content="updated")
    assert mem.content == "User prefers Japanese rice."
    with pytest.raises(ValueError):
        client.update("mem_1")


def test_list_threads_container() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["containerTag"] == "user:jane"
        assert req.url.params["limit"] == "20"
        return httpx.Response(
            200, json={"items": [_memory_record()], "nextCursor": None, "total": 1}
        )

    page = _sync(handler).list()
    assert page.total == 1
    assert page.items[0].scope_key == "user:jane"


# ----- async -----


def _async(handler) -> AsyncMnemo:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    return AsyncMnemo(api_key="test", default_container_tag="user:jane", client=client)


@pytest.mark.asyncio
async def test_async_add_and_search_round_trip() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if req.url.path == "/v1/memories":
            assert set(body) == {"containerTag", "items"}
            return httpx.Response(201, json=_add_response())
        assert req.url.path == "/v1/search"
        assert body == {"q": "rice", "containerTag": "user:jane"}
        return httpx.Response(201, json=_search_response())

    async with _async(handler) as m:
        added = await m.add("User prefers Japanese rice.")
        assert added.items[0].content == "User prefers Japanese rice."
        results = await m.search("rice")
        assert results[0].score == 0.91


@pytest.mark.asyncio
async def test_async_search_container_not_found_returns_empty() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Container not found"})

    async with _async(handler) as m:
        assert await m.search("anything") == []
