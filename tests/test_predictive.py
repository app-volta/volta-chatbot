import pytest

from app.ai.predictive import prever_volume_futuro


def test_prediction_reports_generation_without_claiming_physical_capacity() -> None:
    result = prever_volume_futuro(
        [
            {
                "data_registro": "2026-08-01",
                "peso_total_dia": 10,
            },
            {"data_registro": "2026-08-02", "peso_total_dia": 10},
            {"data_registro": "2026-08-03", "peso_total_dia": 10},
        ],
        dias_futuros=7,
        capacidade_maxima=100,
    )

    assert result["dias_projetados"] == 7
    assert result["volume_atual_kg"] == 30
    assert result["volume_total_registrado_kg"] == 30
    assert result["volume_estimado_kg"] == 100
    assert result["capacidade_maxima_kg"] == 100
    assert result["capacidade_atingida_no_horizonte"] is None
    assert result["dias_ate_lotacao"] is None
    assert result["data_estimada_lotacao"] is None
    assert "peso coletado por ocorrência" in result["motivo_capacidade_indisponivel"]
    assert result["base_calculo"] == "ocorrencias_registradas_historicas"
    assert result["estimativa_nao_e_medicao_fisica"] is True
    assert result["volume_atual_significado"] == "geracao historica; nao representa estoque fisico"
    assert result["requires_human_validation"] is True


def test_prediction_rejects_negative_volume() -> None:
    with pytest.raises(ValueError, match="nao pode ser negativo"):
        prever_volume_futuro(
            [
                {"data_registro": "2026-08-01", "peso_total_dia": -1},
                {"data_registro": "2026-08-02", "peso_total_dia": 2},
            ]
        )


def test_prediction_requires_distinct_dates() -> None:
    result = prever_volume_futuro(
        [
            {"data_registro": "2026-08-01", "peso_total_dia": 1},
            {"data_registro": "2026-08-01", "peso_total_dia": 2},
        ]
    )

    assert "dias diferentes" in result["mensagem"]
