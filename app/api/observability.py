from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.auth import get_observability_access
from app.core.dependencies import get_telemetry
from app.core.observability import Observability

router = APIRouter()


class ResolutionFeedback(BaseModel):
    request_id: UUID
    resolved: bool


@router.get("/summary")
def summary(
    active_users: int = Query(default=100, ge=100, le=1000),
    requests_per_user: int = Query(default=5, ge=1, le=100),
    value_per_resolution_brl: float | None = Query(default=None, gt=0),
    usd_to_brl: float | None = Query(default=None, gt=0),
    _access=Depends(get_observability_access),
    telemetry: Observability = Depends(get_telemetry),
) -> dict:
    """Retorna KPIs e projeção semanal para o painel operacional."""
    return telemetry.weekly_estimate(
        active_users,
        requests_per_user,
        value_per_resolution_brl=value_per_resolution_brl,
        usd_to_brl=usd_to_brl,
    )


@router.post("/resolutions")
def resolution_feedback(
    payload: ResolutionFeedback,
    _access=Depends(get_observability_access),
    telemetry: Observability = Depends(get_telemetry),
) -> dict:
    result = telemetry.record_resolution(str(payload.request_id), payload.resolved)
    if result == "unknown":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request não encontrado na janela operacional.")
    if result == "conflict":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Request já possui feedback contraditório.")
    return {"request_id": str(payload.request_id), "resolved": payload.resolved, "status": result}
