"""Pydantic schemas for the REST API (contract PLAN.md §4.3)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ search
class SearchFilters(BaseModel):
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    geography: Optional[str] = None
    section: Optional[str] = None
    source_type: Optional[str] = None
    confidence_min: Optional[float] = None
    domain: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    filters: Optional[SearchFilters] = None
    role_ctx: Optional[str] = "researcher"


class Citation(BaseModel):
    doc_id: str
    title: Optional[str] = None
    year: Optional[int] = None
    chunk_id: Optional[str] = None
    quote: Optional[str] = None
    # optional enrichment for the source card (contract §4.3 / types.ts Citation)
    section: Optional[str] = None
    source_type: Optional[str] = None
    geography: Optional[str] = None
    journal: Optional[str] = None
    confidence: Optional[str] = None
    page_from: Optional[int] = None
    page_to: Optional[int] = None


class Intent(BaseModel):
    """Contract-shaped intent (types.ts Intent). Internal planner keys collapse here."""
    type: str = "lookup"
    concepts: List[str] = Field(default_factory=list)
    numeric_constraints: Optional[List[str]] = None
    geography: Optional[str] = "all"
    years: Optional[List[int]] = None


class ConfidenceSummary(BaseModel):
    overall: str = "medium"
    n_high: int = 0
    n_medium: int = 0
    n_low: int = 0
    note: Optional[str] = None


class KnowledgeGap(BaseModel):
    id: str
    title: str
    description: str
    severity: str = "medium"


class GraphNode(BaseModel):
    id: str
    type: Optional[str] = None
    name: Optional[str] = None
    name_en: Optional[str] = None
    props: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = None


class GraphEdge(BaseModel):
    id: Optional[str] = None
    src: str
    dst: str
    type: str
    props: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = None


class Subgraph(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


class ExpertRef(BaseModel):
    id: str
    name: Optional[str] = None
    affiliation: Optional[str] = None
    n_works: int = 0


class Contradiction(BaseModel):
    a: str
    b: str
    a_statement: Optional[str] = None
    b_statement: Optional[str] = None


class SearchResponse(BaseModel):
    answer_md: str
    intent: Intent = Field(default_factory=Intent)
    citations: List[Citation] = Field(default_factory=list)
    subgraph: Subgraph = Field(default_factory=Subgraph)
    experts: List[ExpertRef] = Field(default_factory=list)
    contradictions: List[Contradiction] = Field(default_factory=list)
    gaps: List[KnowledgeGap] = Field(default_factory=list)
    confidence_summary: ConfidenceSummary = Field(default_factory=ConfidenceSummary)
    took_ms: int = 0
    search_id: str = ""


# ------------------------------------------------------------------ graph
class NodeNeighborsResponse(BaseModel):
    node: Optional[GraphNode] = None
    neighbors: Subgraph = Field(default_factory=Subgraph)


# ------------------------------------------------------------------ documents
class ChunkModel(BaseModel):
    chunk_id: str
    doc_id: str
    seq: Optional[int] = None
    text: Optional[str] = None
    section_title: Optional[str] = None
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    lang: Optional[str] = None


class DocumentResponse(BaseModel):
    doc_id: str
    title: Optional[str] = None
    section: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    lang: Optional[str] = None
    source_type: Optional[str] = None
    # contract §4.1 / types.ts DocumentMeta uses `geography_hint`; keep `geography`
    # as a defensive alias so older consumers do not break.
    geography_hint: Optional[str] = None
    geography: Optional[str] = None
    n_pages: Optional[int] = None
    n_chunks: Optional[int] = None
    chunks: List[ChunkModel] = Field(default_factory=list)


# ------------------------------------------------------------------ stats / experts
class CoverageBucket(BaseModel):
    key: str
    label: str = ""
    n_docs: int = 0
    n_assertions: int = 0


class YearBucket(BaseModel):
    year: int
    n_docs: int = 0


class StatsResponse(BaseModel):
    n_nodes: int = 0
    n_edges: int = 0
    n_documents: int = 0
    n_assertions: int = 0
    n_contradictions: int = 0
    node_types: Dict[str, int] = Field(default_factory=dict)
    # contract / types.ts StatsResponse: arrays of buckets, not dicts
    by_domain: List[CoverageBucket] = Field(default_factory=list)
    by_section: List[CoverageBucket] = Field(default_factory=list)
    by_year: List[YearBucket] = Field(default_factory=list)
    top_gaps: List[KnowledgeGap] = Field(default_factory=list)
    domain_summaries: Dict[str, Any] = Field(default_factory=dict)
    n_corpus_total: Optional[int] = None
    # C17 analytics extras (frontend ignores; kept for other consumers)
    coverage: Dict[str, Any] = Field(default_factory=dict)
    material_process_gaps: List[Dict[str, Any]] = Field(default_factory=list)
    top_contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    experts: List[ExpertRef] = Field(default_factory=list)


class ExpertsResponse(BaseModel):
    topic: Optional[str] = None
    experts: List[ExpertRef] = Field(default_factory=list)


# ------------------------------------------------------------------ compare
class CompareRow(BaseModel):
    param: str
    tech_a: Optional[str] = None
    tech_b: Optional[str] = None


class CompareResponse(BaseModel):
    tech_a: str
    tech_b: str
    rows: List[CompareRow] = Field(default_factory=list)


# ------------------------------------------------------------------ auth (C13)
class TokenRequest(BaseModel):
    role: str = "researcher"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


# ------------------------------------------------------------------ subscriptions
class SubscriptionRequest(BaseModel):
    query: str
    filters: Optional[SearchFilters] = None
    email: Optional[str] = None


class SubscriptionResponse(BaseModel):
    id: str
    query: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    email: Optional[str] = None
    role: Optional[str] = None
    created_at: str
    last_checked: Optional[str] = None


class SubscriptionListResponse(BaseModel):
    subscriptions: List[SubscriptionResponse] = Field(default_factory=list)


class SubscriptionUpdates(BaseModel):
    id: str
    query: str = ""
    last_checked: Optional[str] = None
    n_new: int = 0
    updates: List[Dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------------------------ edits / review
class EdgePatch(BaseModel):
    author: str
    comment: Optional[str] = None
    props: Optional[Dict[str, Any]] = None


class EdgePatchResponse(BaseModel):
    id: str
    updated: bool
    author: str
    comment: Optional[str] = None
    timestamp: str
    version: int = 1


class ReviewRequest(BaseModel):
    status: str  # confirmed | disputed | rejected
    author: str
    comment: Optional[str] = None


class ReviewResponse(BaseModel):
    id: str
    review_status: str
    author: str
    timestamp: str


# ------------------------------------------------------------------ export / audit
class ExportRequest(BaseModel):
    search_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None   # inline result instead of search_id
    compare: Optional[Dict[str, Any]] = None   # compare table for xlsx
    format: str = "md"  # md | jsonld | pdf | xlsx


class ExportResponse(BaseModel):
    search_id: Optional[str] = None
    format: str
    filename: str
    content: str
    encoding: str = "text"  # text | base64 | base64-html


class AuditEntry(BaseModel):
    ts: str
    role: Optional[str] = None
    endpoint: Optional[str] = None
    action: Optional[str] = None
    params: Optional[Any] = None
    took_ms: Optional[int] = None
    result_counts: Optional[Any] = None


class AuditLogResponse(BaseModel):
    total: int = 0
    limit: int = 100
    offset: int = 0
    entries: List[AuditEntry] = Field(default_factory=list)
