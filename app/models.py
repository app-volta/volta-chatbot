from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

class GuardrailResult(BaseModel):
    blocked: bool
    sanitized_text: str
    reason: str | None = None

# ==============================================================================
# ENUMS
# ==============================================================================
class RouteName(str, Enum):
    TRIAGE = "triage"
    STANDARDS = "standards"
    DATA = "data"
    PERFORMANCE = "performance"
    DIRECT = "direct"
    BLOCKED = "blocked"

# ==============================================================================
# MODELOS DE IA E LANGGRAPH
# ==============================================================================
class SourceCitation(BaseModel):
    source_id: str
    title: str
    corpus: Literal["operational", "regulatory", "cooperatives", "history"]
    location: str | None = None
    url: str | None = None
    score: float | None = None
    excerpt: str = ""
    retrieved_at: datetime | None = None

class RouteDecision(BaseModel):
    route: RouteName
    rationale: str = Field(max_length=300)
    direct_reply: str | None = Field(default=None, max_length=800)

class ProposedOccurrence(BaseModel):
    description: str = Field(min_length=10, max_length=1500)
    category: str = Field(min_length=2, max_length=80)
    requires_sanitization: bool = False

class SpecialistResult(BaseModel):
    proposed_occurrence: ProposedOccurrence | None = None
    metrics_summary: dict | None = None

class JudgeVerdict(BaseModel):
    approved: bool
    reason: str | None = None

class CorporateAnswer(BaseModel):
    title: str | None = None
    answer: str
    recommended_actions: list[str] = Field(default_factory=list)

# ==============================================================================
# REQUESTS & RESPONSES (ENDPOINTS)
# ==============================================================================
class ChatRequest(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    message: str

class ChatResponse(BaseModel):
    request_id: UUID
    session_id: str
    route: RouteName
    response: CorporateAnswer
    citations: list[SourceCitation] = Field(default_factory=list)
    proposed_occurrence: ProposedOccurrence | None = None
    judge: JudgeVerdict | None = None

class OccurrenceDraftCreate(BaseModel):
    tenant_id: str
    plant_id: str
    created_by: str
    proposal: ProposedOccurrence

class OccurrenceDraftResponse(BaseModel):
    draft_id: UUID
    status: str

class ApprovalRequest(BaseModel):
    approved_by: str

class ApprovalResponse(BaseModel):
    occurrence_id: UUID
    status: str

class SessionCreateRequest(BaseModel):
    tenant_id: str
    user_id: str

class SessionResponse(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    created_at: datetime

class ExternalSourceRequest(BaseModel):
    corpus: Literal["operational", "regulatory", "cooperatives", "history"]
    title: str
    url: str

class CollectionRequest(BaseModel):
    cooperative_id: str
    volume_kg: float
    material_type: str
    urgency: Literal["low", "medium", "high"]