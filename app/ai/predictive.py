import pandas as pd
from sklearn.linear_model import LinearRegression
from datetime import timedelta

def prever_volume_futuro(dados_historicos: list[dict], dias_futuros: int = 7) -> dict:
    """
    Recebe o historico do banco e preve o volume acumulado de residuos em quilos para daqui a X dias.
    dados_historicos = [{"data_registro": "2026-08-10", "peso_total_dia": 35.5}, ...]
    """
    if not dados_historicos or len(dados_historicos) < 2:
        return {"alerta": False, "mensagem": "Dados insuficientes para realizar a previsao (minimo de 2 registros)."}

    # 1. Transforma os dados em DataFrame
    df = pd.DataFrame(dados_historicos)
    df['data_registro'] = pd.to_datetime(df['data_registro'])
    
    # 2. Converte as datas para dias passados a partir do primeiro registro
    data_inicial = df['data_registro'].min()
    data_atual = df['data_registro'].max()
    df['dias_passados'] = (df['data_registro'] - data_inicial).dt.days
    
    # Acumula o peso dia apos dia
    df['peso_acumulado'] = df['peso_total_dia'].cumsum()

    # 3. Treina o Modelo de Regressao Linear
    X = df[['dias_passados']]
    y = df['peso_acumulado']
    
    modelo = LinearRegression()
    modelo.fit(X, y)
    
    taxa_crescimento_diaria = modelo.coef_[0]
    
    # 4. Projeta o dia futuro com base no ultimo registro
    dias_totais_ultimo_registro = (data_atual - data_inicial).days
    dia_alvo = dias_totais_ultimo_registro + dias_futuros
    
    # Executa a predicao do modelo
    volume_previsto = modelo.predict([[dia_alvo]])[0]
    data_projetada = data_atual + timedelta(days=dias_futuros)
    
    return {
        "sucesso": True,
        "dias_projetados": dias_futuros,
        "data_projetada": data_projetada.strftime("%Y-%m-%d"),
        "taxa_geracao_diaria_kg": round(float(taxa_crescimento_diaria), 2),
        "volume_estimado_kg": round(float(volume_previsto), 2)
    }