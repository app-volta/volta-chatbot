from app.db.models import AnaliseResiduoIA

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