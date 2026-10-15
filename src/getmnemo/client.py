"""Sync + async Mnemo clients.

Both clients share the same surface; the async one is suitable for use inside
LangGraph nodes, FastAPI routes, or any other event-loop-friendly codebase.

Wire contract (mirrors the TypeScript ``getmnemo`` 0.6 SDK):

- ``POST /v1/memories``  body ``{containerTag, items: [{content, metadata?}]}``
- ``POST /v1/search``    body ``{q, containerTag, limit?}`` -> ``{results: [...]}``

Every call needs a container tag of the form ``"<type>:<id>"`` (for example
``"user:jane"``) — per call, via ``default_container_tag``, or via the
``GETMNEMO_CONTAINER_TAG`` environment variable.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from collections.abc import Awaitable, Mapping, Sequence
from typing import Any, Callable, TypeVar, Union
from urllib.parse import quote

import httpx
from typing_extensions import Self, TypeAlias

from .errors import MnemoHTTPError
from .models import AddResponse, Memory, PaginatedMemories, SearchHit

_DEFAULT_BASE_URL = "https://api.mnemohq.com"
_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "getmnemo-python/0.2.0"
_DEFAULT_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.2
_RETRY_MAX_DELAY = 5.0
_MAX_BATCH_SIZE = 100

# snake_case input keys accepted in add_many items -> camelCase wire keys.
_ITEM_KEY_MAP = {
    "content": "content",
    "metadata": "metadata",
    "idempotency_key": "idempotencyKey",
    "memory_type": "memoryType",
}

T = TypeVar("T")
MemoryItemInput: TypeAlias = Union[str, Mapping[str, Any]]


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with full jitter."""
    capped = min(_RETRY_BASE_DELAY * (2**attempt), _RETRY_MAX_DELAY)
    return random.uniform(0, capped)


def _is_retryable_status(status: int) -> bool:
    # 501 Not Implemented is a permanent failure — retrying wastes round-trips.
    if status == 501:
        return False
    return status == 429 or 500 <= status < 600


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a Retry-After header (seconds or HTTP-date). Returns ``None`` if absent or invalid."""
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    try:
        # Delta-seconds form.
        secs = float(raw)
        return max(0.0, min(secs, _RETRY_MAX_DELAY))
    except ValueError:
        pass
    try:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(raw)
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, min(delta, _RETRY_MAX_DELAY))
    except (TypeError, ValueError):
        return None


def _delay_for(resp: httpx.Response, attempt: int) -> float:
    server_hint = _retry_after_seconds(resp)
    if server_hint is not None:
        return server_hint
    return _retry_delay(attempt)


def _send_with_retries(
    fn: Callable[[], httpx.Response],
    max_retries: int,
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            resp = fn()
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt >= max_retries:
                raise
            time.sleep(_retry_delay(attempt))
            attempt += 1
            continue
        if _is_retryable_status(resp.status_code) and attempt < max_retries:
            time.sleep(_delay_for(resp, attempt))
            attempt += 1
            continue
        return resp


async def _send_with_retries_async(
    fn: Callable[[], Awaitable[httpx.Response]],
    max_retries: int,
) -> httpx.Response:
    attempt = 0
    while True:
        try:
            resp = await fn()
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt >= max_retries:
                raise
            await asyncio.sleep(_retry_delay(attempt))
            attempt += 1
            continue
        if _is_retryable_status(resp.status_code) and attempt < max_retries:
            await asyncio.sleep(_delay_for(resp, attempt))
            attempt += 1
            continue
        return resp


def _resolve_api_key(value: str | None) -> str:
    resolved = value or os.environ.get("GETMNEMO_API_KEY")
    if not resolved:
        raise ValueError(
            "api_key is required. Pass it explicitly or set $GETMNEMO_API_KEY.",
        )
    return resolved


def _headers(api_key: str, workspace_id: str | None) -> dict[str, str]:
    h = {
        "authorization": f"Bearer {api_key}",
        "user-agent": _USER_AGENT,
        "content-type": "application/json",
    }
    if workspace_id:
        # Deprecated: workspace identity now comes from the API key. Sent only
        # when explicitly configured, for backwards compatibility.
        h["x-workspace-id"] = workspace_id
    return h


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    body: Any
    try:
        body = resp.json()
        message = body.get("message") if isinstance(body, dict) else str(body)
    except ValueError:
        body = resp.text
        message = body or resp.reason_phrase
    raise MnemoHTTPError(message or "Unknown error", resp.status_code, body)


def _is_container_not_found(resp: httpx.Response) -> bool:
    """True only for the API's 404 "Container not found" (never-written container)."""
    if resp.status_code != 404:
        return False
    try:
        body = resp.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    return "container not found" in str(body.get("message", "")).lower()


def _build_items(
    items: Sequence[MemoryItemInput], *, auto_idempotency_key: bool = False
) -> list[dict[str, Any]]:
    """Normalize add_many items to the wire shape, rejecting unknown keys.

    The API's global validation rejects unknown body keys with a 400, so we
    fail fast client-side with a clearer message.
    """
    if not 1 <= len(items) <= _MAX_BATCH_SIZE:
        raise ValueError(f"add_many() takes between 1 and {_MAX_BATCH_SIZE} items")
    built: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            built.append(_with_key({"content": item}, auto_idempotency_key))
            continue
        unknown = set(item) - set(_ITEM_KEY_MAP)
        if unknown:
            raise ValueError(
                f"add_many() item {index} has unknown key(s) {sorted(unknown)}; "
                f"allowed keys: {sorted(_ITEM_KEY_MAP)}"
            )
        if not item.get("content"):
            raise ValueError(f"add_many() item {index} requires a non-empty 'content'")
        built.append(
            _with_key(
                {_ITEM_KEY_MAP[key]: value for key, value in item.items() if value is not None},
                auto_idempotency_key,
            )
        )
    return built


def _with_key(item: dict[str, Any], auto: bool) -> dict[str, Any]:
    """Add a generated idempotencyKey so a retried write cannot duplicate.

    Generated once per call (the payload is built before the retry loop), so
    every retry of the same request carries the same key.
    """
    if auto and "idempotencyKey" not in item:
        return {**item, "idempotencyKey": str(uuid.uuid4())}
    return item


def _search_payload(q: str, container_tag: str, limit: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"q": q, "containerTag": container_tag}
    if limit is not None:
        payload["limit"] = limit
    return payload


def _parse_search_results(data: Any) -> list[SearchHit]:
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    return [SearchHit.model_validate(hit) for hit in results]


class _BaseClient:
    """Configuration shared by the sync and async clients."""

    def __init__(
        self,
        api_key: str | None,
        *,
        default_container_tag: str | None,
        workspace_id: str | None,
        base_url: str | None,
        max_retries: int,
    ) -> None:
        self._api_key = _resolve_api_key(api_key)
        self._default_container_tag = default_container_tag or os.environ.get(
            "GETMNEMO_CONTAINER_TAG"
        )
        self._workspace_id = workspace_id or os.environ.get("GETMNEMO_WORKSPACE_ID")
        self._base_url = (
            base_url or os.environ.get("GETMNEMO_API_URL") or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._max_retries = max(0, int(max_retries))

    def _require_container(self, method: str, container_tag: str | None) -> str:
        tag = container_tag or self._default_container_tag
        if not tag:
            raise ValueError(
                f"{method}: a container is required — pass container_tag "
                '(a "<type>:<id>" string such as "user:jane") per call, set '
                "default_container_tag on the client, or set $GETMNEMO_CONTAINER_TAG."
            )
        return tag

    def _container_params(self, container_tag: str | None) -> dict[str, str]:
        """Optional container for the by-id and list routes.

        These routes stay callable without a container so the API remains the
        single source of truth on whether one is mandatory.
        """
        tag = container_tag or self._default_container_tag
        return {"containerTag": tag} if tag else {}


class Mnemo(_BaseClient):
    """Synchronous Mnemo Memory client.

    All public methods make a single HTTP round-trip and return typed Pydantic
    models. The underlying httpx.Client is created on first use and reused.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        default_container_tag: str | None = None,
        workspace_id: str | None = None,
        base_url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        super().__init__(
            api_key,
            default_container_tag=default_container_tag,
            workspace_id=workspace_id,
            base_url=base_url,
            max_retries=max_retries,
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=_headers(self._api_key, self._workspace_id),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ----- public API -----

    def search(
        self,
        q: str,
        *,
        container_tag: str | None = None,
        limit: int | None = None,
    ) -> list[SearchHit]:
        """Hybrid retrieval. Returns the ranked results list.

        A container that has never been written to currently yields a 404
        ("Container not found"); that is treated as empty results. An upcoming
        API change returns an empty list instead — both shapes are handled.
        """
        tag = self._require_container("search()", container_tag)
        resp = _send_with_retries(
            lambda: self._client.post("/v1/search", json=_search_payload(q, tag, limit)),
            self._max_retries,
        )
        if _is_container_not_found(resp):
            return []
        _raise_for_status(resp)
        return _parse_search_results(resp.json())

    def add(
        self,
        content: str,
        *,
        container_tag: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AddResponse:
        """Store a single atomic fact."""
        item: dict[str, Any] = {"content": content}
        if metadata is not None:
            item["metadata"] = metadata
        return self.add_many([item], container_tag=container_tag)

    def add_many(
        self,
        items: Sequence[MemoryItemInput],
        *,
        container_tag: str | None = None,
    ) -> AddResponse:
        """Store between 1 and 100 memories in one request.

        Each item is a content string or a mapping with ``content`` plus
        optional ``metadata``, ``idempotency_key``, and ``memory_type``.
        """
        tag = self._require_container("add_many()", container_tag)
        payload = {
            "containerTag": tag,
            "items": _build_items(items, auto_idempotency_key=self._max_retries > 0),
        }
        resp = _send_with_retries(
            lambda: self._client.post("/v1/memories", json=payload),
            self._max_retries,
        )
        _raise_for_status(resp)
        return AddResponse.model_validate(resp.json())

    def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        container_tag: str | None = None,
    ) -> Memory:
        payload: dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if metadata is not None:
            payload["metadata"] = metadata
        if not payload:
            raise ValueError("update() requires at least one of content/metadata")
        resp = _send_with_retries(
            lambda: self._client.patch(
                f"/v1/memories/{quote(memory_id, safe='')}",
                json=payload,
                params=self._container_params(container_tag),
            ),
            self._max_retries,
        )
        _raise_for_status(resp)
        return Memory.model_validate(resp.json())

    def delete(self, memory_id: str, *, container_tag: str | None = None) -> None:
        resp = _send_with_retries(
            lambda: self._client.delete(
                f"/v1/memories/{quote(memory_id, safe='')}",
                params=self._container_params(container_tag),
            ),
            self._max_retries,
        )
        _raise_for_status(resp)

    def list(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        container_tag: str | None = None,
    ) -> PaginatedMemories:
        params: dict[str, Any] = {"limit": limit, **self._container_params(container_tag)}
        if cursor is not None:
            params["cursor"] = cursor
        resp = _send_with_retries(
            lambda: self._client.get("/v1/memories", params=params),
            self._max_retries,
        )
        _raise_for_status(resp)
        return PaginatedMemories.model_validate(resp.json())


class AsyncMnemo(_BaseClient):
    """Asynchronous variant of :class:`Mnemo`.

    Use as an async context manager so the underlying connection pool is
    closed deterministically.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        default_container_tag: str | None = None,
        workspace_id: str | None = None,
        base_url: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        super().__init__(
            api_key,
            default_container_tag=default_container_tag,
            workspace_id=workspace_id,
            base_url=base_url,
            max_retries=max_retries,
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=_headers(self._api_key, self._workspace_id),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(
        self,
        q: str,
        *,
        container_tag: str | None = None,
        limit: int | None = None,
    ) -> list[SearchHit]:
        """Hybrid retrieval. Returns the ranked results list.

        A container that has never been written to currently yields a 404
        ("Container not found"); that is treated as empty results. An upcoming
        API change returns an empty list instead — both shapes are handled.
        """
        tag = self._require_container("search()", container_tag)
        resp = await _send_with_retries_async(
            lambda: self._client.post("/v1/search", json=_search_payload(q, tag, limit)),
            self._max_retries,
        )
        if _is_container_not_found(resp):
            return []
        _raise_for_status(resp)
        return _parse_search_results(resp.json())

    async def add(
        self,
        content: str,
        *,
        container_tag: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AddResponse:
        """Store a single atomic fact."""
        item: dict[str, Any] = {"content": content}
        if metadata is not None:
            item["metadata"] = metadata
        return await self.add_many([item], container_tag=container_tag)

    async def add_many(
        self,
        items: Sequence[MemoryItemInput],
        *,
        container_tag: str | None = None,
    ) -> AddResponse:
        """Store between 1 and 100 memories in one request.

        Each item is a content string or a mapping with ``content`` plus
        optional ``metadata``, ``idempotency_key``, and ``memory_type``.
        """
        tag = self._require_container("add_many()", container_tag)
        payload = {
            "containerTag": tag,
            "items": _build_items(items, auto_idempotency_key=self._max_retries > 0),
        }
        resp = await _send_with_retries_async(
            lambda: self._client.post("/v1/memories", json=payload),
            self._max_retries,
        )
        _raise_for_status(resp)
        return AddResponse.model_validate(resp.json())

    async def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        container_tag: str | None = None,
    ) -> Memory:
        payload: dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if metadata is not None:
            payload["metadata"] = metadata
        if not payload:
            raise ValueError("update() requires at least one of content/metadata")
        resp = await _send_with_retries_async(
            lambda: self._client.patch(
                f"/v1/memories/{quote(memory_id, safe='')}",
                json=payload,
                params=self._container_params(container_tag),
            ),
            self._max_retries,
        )
        _raise_for_status(resp)
        return Memory.model_validate(resp.json())

    async def delete(self, memory_id: str, *, container_tag: str | None = None) -> None:
        resp = await _send_with_retries_async(
            lambda: self._client.delete(
                f"/v1/memories/{quote(memory_id, safe='')}",
                params=self._container_params(container_tag),
            ),
            self._max_retries,
        )
        _raise_for_status(resp)

    async def list(
        self,
        *,
        limit: int = 20,
        cursor: str | None = None,
        container_tag: str | None = None,
    ) -> PaginatedMemories:
        params: dict[str, Any] = {"limit": limit, **self._container_params(container_tag)}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await _send_with_retries_async(
            lambda: self._client.get("/v1/memories", params=params),
            self._max_retries,
        )
        _raise_for_status(resp)
        return PaginatedMemories.model_validate(resp.json())
