"""Pydantic models mirroring the Mnemo REST API.

Field names are snake_case in Python and map onto the camelCase wire format
via aliases. Models ignore unknown response fields so additive API changes
never break parsing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Memory(_Base):
    """A stored memory record (``MemoryRecordDto``)."""

    id: str
    content: str
    scope_key: str | None = Field(default=None, alias="scopeKey")
    memory_type: str | None = Field(default=None, alias="memoryType")
    metadata: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")
    source_document_id: str | None = Field(default=None, alias="sourceDocumentId")
    due_at: datetime | None = Field(default=None, alias="dueAt")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    deleted_at: datetime | None = Field(default=None, alias="deletedAt")


class MemoryWriteStats(_Base):
    total: int
    created: int
    deduplicated: int


class MemoryWriteReceiptItem(_Base):
    input_index: int = Field(alias="inputIndex")
    memory_id: str = Field(alias="memoryId")
    status: str
    search_status: str | None = Field(default=None, alias="searchStatus")


class MemoryWriteReceipt(_Base):
    write_id: str = Field(alias="writeId")
    status: str
    searchable_at: datetime | None = Field(default=None, alias="searchableAt")
    items: list[MemoryWriteReceiptItem] = Field(default_factory=list)


class AddResponse(_Base):
    """Response of ``POST /v1/memories`` (``CreateMemoriesResponseDto``)."""

    scope_key: str = Field(alias="scopeKey")
    items: list[Memory]
    stats: MemoryWriteStats | None = None
    receipt: MemoryWriteReceipt | None = None


class SearchHit(_Base):
    """One ranked result from ``POST /v1/search`` (``SearchResultDto``)."""

    result_type: str = Field(alias="resultType")
    score: float
    scope_key: str = Field(alias="scopeKey")
    content: str
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = Field(default=None, alias="createdAt")
    # Set when result_type is "memory".
    memory_id: str | None = Field(default=None, alias="memoryId")
    # Set when result_type is "document", and on memories derived from one.
    document_id: str | None = Field(default=None, alias="documentId")
    # Set when result_type is "fact".
    fact_id: str | None = Field(default=None, alias="factId")
    memory_type: str | None = Field(default=None, alias="memoryType")
    content_type: str | None = Field(default=None, alias="contentType")
    polarity: str | None = None
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    # Provenance / per-strategy scores; present only with includeSources=true.
    sources: dict[str, Any] | None = None


class PaginatedMemories(_Base):
    items: list[Memory]
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    total: int | None = None
