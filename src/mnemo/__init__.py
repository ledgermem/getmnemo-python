"""Backwards-compatible alias for the ``getmnemo`` package.

0.1.x shipped the module as ``mnemo``; the canonical import name now matches
the install name: ``from getmnemo import Mnemo``.
"""

from getmnemo import (
    AddResponse,
    AsyncMnemo,
    Memory,
    MemoryWriteReceipt,
    MemoryWriteReceiptItem,
    MemoryWriteStats,
    Mnemo,
    MnemoError,
    MnemoHTTPError,
    PaginatedMemories,
    SearchHit,
    __version__,
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
    "__version__",
]
