from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_telemetry
from app.core.observability import Observability

router = APIRouter()


@router.get("/summary")
def summary(
    active_users: int = Query(default=100, ge=100, le=1000),
    requests_per_user: int = Query(default=5, ge=1, le=100),
    telemetry: Observability = Depends(get_telemetry),
) -> dict:
    """Retorna KPIs e projeção semanal para o painel operacional."""
    return telemetry.weekly_estimate(active_users, requests_per_user)
