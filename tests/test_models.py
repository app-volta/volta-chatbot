from uuid import UUID

from app.db.models import AnaliseResiduoIA, OccurrenceDraftCreate

def test_analise_residuo_ia_deve_aceitar_mobile_summary():
    dados = {
        "detected_waste_type": "Plástico Reciclável",
        "ai_contamination_level": "BAIXO",
        "estimated_quantity_kg": 15.5,
        "recommendations": "Descartar na lixeira vermelha",
        "report_text": "Laudo completo da visão computacional.",
        "mobile_summary": "Lixo reciclável detectado, descarte na lixeira vermelha."
    }
    
    modelo = AnaliseResiduoIA(**dados)
    
    assert modelo.mobile_summary == "Lixo reciclável detectado, descarte na lixeira vermelha."
    assert modelo.ai_contamination_level == "BAIXO"


def test_occurrence_draft_uses_remote_uuid_identifiers():
    payload = OccurrenceDraftCreate(
        company_id="550e8400-e29b-41d4-a716-446655440000",
        area_id="550e8400-e29b-41d4-a716-446655440001",
        user_id="550e8400-e29b-41d4-a716-446655440002",
        ai_data={
            "detected_waste_type": "Plastico",
            "ai_contamination_level": "BAIXO",
            "recommendations": "Segregar",
            "report_text": "Laudo",
            "mobile_summary": "Plastico identificado",
        },
    )

    assert isinstance(payload.company_id, UUID)
    assert payload.priority == "MEDIA"
