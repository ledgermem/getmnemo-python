# getmnemo

Python SDK for [Mnemo Memory](https://mnemohq.com) — long-term memory infrastructure for AI agents.

```bash
pip install getmnemo
```

## Quickstart

```python
from mnemo import Mnemo

memory = Mnemo(api_key="lk_live_...", workspace_id="ws_...")

# Store an atomic fact
memory.add("User prefers Japanese short-grain rice for onigiri.")

# Retrieve relevant facts
hits = memory.search("what kind of rice does the user like?")
for hit in hits.hits:
    print(f"{hit.score:.2f}  {hit.content}")
```

Async variant:

```python
import asyncio
from mnemo import AsyncMnemo

async def main() -> None:
    async with AsyncMnemo(api_key="...", workspace_id="...") as m:
        await m.add("Trip to Costa Rica was 5 days, brought 7 shirts.")
        res = await m.search("how many shirts did I pack?")
        print(res.hits[0].content)

asyncio.run(main())
```

## Configuration

The client reads from env vars when arguments are not passed explicitly:

| Env var | Default | Notes |
|---|---|---|
| `GETMNEMO_API_KEY` | (required) | from <https://app.mnemohq.com/settings/api-keys> |
| `GETMNEMO_WORKSPACE_ID` | (required) | from the dashboard URL |
| `GETMNEMO_ACTOR_ID` | none | optional — scopes calls to a single user |
| `GETMNEMO_API_URL` | `https://api.mnemohq.com` | override for self-hosted |

## API surface

| Method | Purpose |
|---|---|
| `search(query, *, limit=8, actor_id=None)` | Hybrid 7-strategy retrieval. Returns `SearchResponse`. |
| `add(content, *, metadata=None, actor_id=None)` | Store an atomic fact. Returns `Memory`. |
| `update(memory_id, *, content=None, metadata=None)` | Patch existing memory. |
| `delete(memory_id)` | Remove a memory. |
| `list(*, limit=20, cursor=None, actor_id=None)` | Cursor-paginated list. |

All methods exist on both `Mnemo` (sync) and `AsyncMnemo` (async).

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## License

MIT
