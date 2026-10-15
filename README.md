# getmnemo

Python SDK for [Mnemo Memory](https://mnemohq.com) — long-term memory infrastructure for AI agents.

```bash
pip install getmnemo
```

## Quickstart

```python
from getmnemo import Mnemo

memory = Mnemo(api_key="prfly_live_...", default_container_tag="user:jane")

# Store an atomic fact
memory.add("User prefers Japanese short-grain rice for onigiri.")

# Retrieve relevant facts — returns a list of ranked hits
results = memory.search("what kind of rice does the user like?")
for hit in results:
    print(f"{hit.score:.2f}  {hit.content}")
```

Every call is scoped to a **container** — a `"<type>:<id>"` string such as
`"user:jane"` or `"project:alpha"`. Set it once on the client
(`default_container_tag=`) or per call (`container_tag=`). Searching a
container that has never been written to returns an empty list.

Async variant:

```python
import asyncio
from getmnemo import AsyncMnemo

async def main() -> None:
    async with AsyncMnemo(api_key="...", default_container_tag="user:jane") as m:
        await m.add("Trip to Costa Rica was 5 days, brought 7 shirts.")
        results = await m.search("how many shirts did I pack?")
        if results:
            print(results[0].content)

asyncio.run(main())
```

## Configuration

The client reads from env vars when arguments are not passed explicitly:

| Env var | Default | Notes |
|---|---|---|
| `GETMNEMO_API_KEY` | (required) | from <https://app.mnemohq.com/settings/api-keys> |
| `GETMNEMO_CONTAINER_TAG` | none | default container, e.g. `user:jane` |
| `GETMNEMO_WORKSPACE_ID` | none | deprecated — identity comes from the API key |
| `GETMNEMO_API_URL` | `https://api.mnemohq.com` | override for self-hosted |

## API surface

| Method | Purpose |
|---|---|
| `search(q, *, container_tag=None, limit=None)` | Hybrid retrieval. Returns `list[SearchHit]`. |
| `add(content, *, container_tag=None, metadata=None)` | Store an atomic fact. Returns `AddResponse`. |
| `add_many(items, *, container_tag=None)` | Store 1–100 memories in one request. Returns `AddResponse`. |
| `update(memory_id, *, content=None, metadata=None, container_tag=None)` | Patch existing memory. |
| `delete(memory_id, *, container_tag=None)` | Remove a memory. |
| `list(*, limit=20, cursor=None, container_tag=None)` | Cursor-paginated list. |

All methods exist on both `Mnemo` (sync) and `AsyncMnemo` (async).

`add_many` items are content strings or mappings:

```python
memory.add_many([
    "Standup moved to 9:30.",
    {"content": "Invoices are net-30.", "memory_type": "fact", "idempotency_key": "inv-policy-1"},
])
```

### Upgrading from 0.1.x

0.2.0 tracks the current Mnemo API; 0.1.x requests are rejected by it.

- `workspace_id` is no longer required (the API key carries identity); pass a
  container instead: `Mnemo(api_key=..., default_container_tag="user:jane")`.
- `search("q")` now returns a `list[SearchHit]` (was `SearchResponse.hits`).
- `add(...)` now returns an `AddResponse` (was a single `Memory`).
- `actor_id` was removed — use per-user container tags.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## License

MIT
