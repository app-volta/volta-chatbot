from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID
from typing import Optional
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
    triage_analysis: TriageAnalysis | None = None

class JudgeVerdict(BaseModel):
    approved: bool
    reason: str | None = None

class CorporateAnswer(BaseModel):
    title: str | None = None
    answer: str
    recommended_actions: list[str] = Field(default_factory=list)

# ==============================================================================
# O CONTRATO DA IA PREDITIVA (Visão Computacional)
# ==============================================================================
class AnaliseResiduoIA(BaseModel):
    detected_waste_type: str = Field(
        description="O tipo de resíduo identificado na imagem (ex: Papelão contaminado, Óleo lubrificante, Plástico reciclável)."
    )
    ai_contamination_level: str = Field(
        description="Nível de contaminação estimado: 'BAIXO', 'MEDIO' ou 'ALTO'."
    )
    estimated_quantity_kg: Optional[float] = Field(
        None, 
        description="Estimativa visual de peso em kg. Se não for possível deduzir pela imagem, retorne null."
    )
    recommendations: str = Field(
        description="Passo a passo de segurança para manuseio, EPIs necessários e qual o descarte correto."
    )
    report_text: str = Field(
        description="Um laudo descritivo resumindo o que foi detectado na imagem."
    )    
    mobile_summary: str = Field(
        description="Resumo ultra curto de no máximo 20 palavras focado no mobile para caber no card verde."
    )

# ==============================================================================
# REQUESTS & RESPONSES (ENDPOINTS)
# ==============================================================================
class ChatRequest(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    message: str
    image_base64: str | None = None

class ChatResponse(BaseModel):
    request_id: UUID
    session_id: str
    route: RouteName
    response: CorporateAnswer
    citations: list[SourceCitation] = Field(default_factory=list)
    proposed_occurrence: ProposedOccurrence | None = None
    triage_analysis: TriageAnalysis | None = None
    judge: JudgeVerdict | None = None

class OccurrenceDraftCreate(BaseModel):
    company_id: int
    area_id: int
    user_id: int
    ai_data: AnaliseResiduoIA 

class OccurrenceDraftResponse(BaseModel):
    draft_id: int
    status: str

class ApprovalRequest(BaseModel):
    approved_by: str

class ApprovalResponse(BaseModel):
    occurrence_id: int
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