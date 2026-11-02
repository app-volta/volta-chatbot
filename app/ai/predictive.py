"""Previsao numerica de volume para apoiar o planejamento operacional."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite

import pandas as pd
from sklearn.linear_model import LinearRegression


def prever_volume_futuro(
    dados_historicos: list[dict],
    dias_futuros: int = 7,
    capacidade_maxima: float | None = None,
) -> dict:
    """Projeta a geração acumulada das ocorrências registradas.

    ``dados_historicos`` deve conter ``data_registro`` e ``peso_total_dia`` e já
    estar filtrado pela persistência. O saldo é documental; não mede fisicamente
    a caçamba e sempre exige conferência operacional.
    """
    if len(dados_historicos) < 2:
        return {"alerta": False, "mensagem": "Dados insuficientes para realizar a previsao (minimo de 2 registros)."}
    if dias_futuros < 0:
        raise ValueError("dias_futuros deve ser maior ou igual a zero.")
    if capacidade_maxima is not None and (not isfinite(capacidade_maxima) or capacidade_maxima <= 0):
        raise ValueError("capacidade_maxima deve ser maior que zero.")

    df = pd.DataFrame(dados_historicos)
    required = {"data_registro", "peso_total_dia"}
    if not required.issubset(df.columns):
        raise ValueError("O historico deve conter data_registro e peso_total_dia.")

    df["data_registro"] = pd.to_datetime(df["data_registro"], errors="coerce")
    df["peso_total_dia"] = pd.to_numeric(df["peso_total_dia"], errors="coerce")
    if df[["data_registro", "peso_total_dia"]].isna().any().any():
        raise ValueError("O historico contem data ou volume invalido.")
    if (df["peso_total_dia"] < 0).any():
        raise ValueError("O volume diario nao pode ser negativo.")

    df = df.sort_values("data_registro").reset_index(drop=True)
    data_inicial = df["data_registro"].min()
    data_atual = df["data_registro"].max()
    df["dias_passados"] = (df["data_registro"] - data_inicial).dt.days
    if df["dias_passados"].nunique() < 2:
        return {"alerta": False, "mensagem": "Dados insuficientes: sao necessarios registros em dias diferentes."}

    df["peso_acumulado"] = df["peso_total_dia"].cumsum()
    modelo = LinearRegression().fit(df[["dias_passados"]], df["peso_acumulado"])

    dias_ultimo_registro = int((data_atual - data_inicial).days)
    dia_alvo = dias_ultimo_registro + dias_futuros
    volume_previsto = max(0.0, float(modelo.predict(pd.DataFrame({"dias_passados": [dia_alvo]}))[0]))
    taxa_diaria = float(modelo.coef_[0])
    volume_historico = float(df["peso_acumulado"].iloc[-1])
    resultado = {
        "sucesso": True,
        "dias_projetados": dias_futuros,
        "data_projetada": (data_atual + timedelta(days=dias_futuros)).strftime("%Y-%m-%d"),
        "taxa_geracao_diaria_kg": round(taxa_diaria, 2),
        # Compatibilidade: este campo representa geração histórica, não estoque físico.
        "volume_atual_kg": round(volume_historico, 2),
        "volume_total_registrado_kg": round(volume_historico, 2),
        "volume_estimado_kg": round(volume_previsto, 2),
        "base_calculo": "ocorrencias_registradas_historicas",
        "volume_atual_significado": "geracao historica; nao representa estoque fisico",
        "estimativa_nao_e_medicao_fisica": True,
        "requires_human_validation": True,
    }

    if capacidade_maxima is not None:
        resultado.update(
            {
                "capacidade_maxima_kg": round(capacidade_maxima, 2),
                "capacidade_atingida_no_horizonte": None,
                "dias_ate_lotacao": None,
                "data_estimada_lotacao": None,
                "motivo_capacidade_indisponivel": "O peso coletado por ocorrência não está disponível para calcular o estoque restante.",
            }
        )
    return resultado
