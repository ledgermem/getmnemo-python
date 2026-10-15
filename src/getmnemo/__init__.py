"""Mnemo Memory — Python SDK.

Quickstart:

    from getmnemo import Mnemo

    memory = Mnemo(api_key="prfly_live_...", default_container_tag="user:jane")
    memory.add("User prefers Japanese short-grain rice for onigiri.")
    results = memory.search("what kind of rice does the user like?")
    for hit in results:
        print(hit.score, hit.content)

Async variant:

    import asyncio
    from getmnemo import AsyncMnemo

    async def main() -> None:
        async with AsyncMnemo(api_key="...", default_container_tag="user:jane") as m:
            await m.add("Trip to Costa Rica was 5 days, brought 7 shirts.")
            results = await m.search("how many shirts did I pack for Costa Rica?")
            if results:
                print(results[0].content)

    asyncio.run(main())
"""

from .client import AsyncMnemo, Mnemo
from .errors import MnemoError, MnemoHTTPError
from .models import (
    AddResponse,
    Memory,
    MemoryWriteReceipt,
    MemoryWriteReceiptItem,
    MemoryWriteStats,
    PaginatedMemories,
    SearchHit,
)

__all__ = [
    "AddResponse",
    "AsyncMnemo",
    "Memory",
    "MemoryWriteReceipt",
    "MemoryWriteReceiptItem",
    "MemoryWriteStats",
    "Mnemo",
    "MnemoError",
    "MnemoHTTPError",
    "PaginatedMemories",
    "SearchHit",
]

__version__ = "0.2.0"
