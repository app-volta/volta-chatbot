import pytest

from app.ai.predictive import prever_volume_futuro


def test_prediction_uses_days_and_reports_capacity_separately() -> None:
    result = prever_volume_futuro(
        [
            {"data_registro": "2026-08-01", "peso_total_dia": 10},
            {"data_registro": "2026-08-02", "peso_total_dia": 10},
            {"data_registro": "2026-08-03", "peso_total_dia": 10},
        ],
        dias_futuros=7,
        capacidade_maxima=100,
    )

    assert result["dias_projetados"] == 7
    assert result["volume_atual_kg"] == 30
    assert result["volume_estimado_kg"] == 100
    assert result["capacidade_maxima_kg"] == 100
    assert result["dias_ate_lotacao"] == 7


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
