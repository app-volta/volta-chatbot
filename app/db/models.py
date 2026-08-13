from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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

# 👇 NOVO MODELO: Estrutura para preencher a Tela 3 (Análise da IA)
class TriageAnalysis(BaseModel):
    tipo_material: str = Field(description="Ex: Papelão Classe A, Sucata metálica, Plástico Multicamada")
    contaminacao: str = Field(description="Ex: Baixa, Média, Alta")
    quantidade_estimada: str = Field(description="Estimativa de peso. Ex: ≈ 38 kg")
    unidades: str | None = Field(default=None, description="Ex: 11 un. (caixas/fardos)")
    confianca_ia: int = Field(description="Porcentagem de certeza da IA (0 a 100)")
    recomendacao_automatica: str = Field(description="Dica curta de armazenamento. Ex: Guarde num lugar seco.")

class SpecialistResult(BaseModel):
    proposed_occurrence: ProposedOccurrence | None = None
    metrics_summary: dict | None = None
    # 👇 Adicionamos a análise da triagem no resultado do especialista
    triage_analysis: TriageAnalysis | None = None

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
    # 👇 Novo campo opcional pra receber a foto da câmera convertida em texto!
    image_base64: str | None = None

class ChatResponse(BaseModel):
    request_id: UUID
    session_id: str
    route: RouteName
    response: CorporateAnswer
    citations: list[SourceCitation] = Field(default_factory=list)
    proposed_occurrence: ProposedOccurrence | None = None
    # 👇 O Front-end vai puxar os dados visuais daqui para montar a tela!
    triage_analysis: TriageAnalysis | None = None
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
    
class GuardrailResult(BaseModel):
    allowed: bool
    reason: str | None = None