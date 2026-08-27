import pandas as pd
from sklearn.linear_model import LinearRegression
from datetime import timedelta

def prever_lotacao_cacamba(dados_historicos: list[dict], capacidade_maxima_kg: float) -> dict:
    """
    Recebe o historico do banco e preve em quantos dias a cacamba vai lotar.
    dados_historicos = [{"data_registro": "2026-08-10", "peso_total_dia": 35.5}, ...]
    """
    if not dados_historicos or len(dados_historicos) < 2:
        return {"alerta": False, "mensagem": "Dados insuficientes para realizar a previsao (minimo de 2 registros)."}

    # 1. Transforma os dados em DataFrame
    df = pd.DataFrame(dados_historicos)
    df['data_registro'] = pd.to_datetime(df['data_registro'])
    
    # 2. Converte as datas para dias passados a partir do primeiro registro
    data_inicial = df['data_registro'].min()
    df['dias_passados'] = (df['data_registro'] - data_inicial).dt.days
    
    # Acumula o peso dia apos dia
    df['peso_acumulado'] = df['peso_total_dia'].cumsum()

    # 3. Treina o Modelo de Regressao Linear
    X = df[['dias_passados']]
    y = df['peso_acumulado']
    
    modelo = LinearRegression()
    modelo.fit(X, y)
    
    taxa_crescimento_diaria = modelo.coef_[0]
    
    if taxa_crescimento_diaria <= 0:
        return {"alerta": False, "mensagem": "A geracao de residuos esta estavel ou caindo. Sem risco iminente de lotacao."}

    # Calcula em qual dia o peso atinge a capacidade maxima
    dias_para_lotar = (capacidade_maxima_kg - modelo.intercept_) / taxa_crescimento_diaria
    
    data_prevista = data_inicial + timedelta(days=int(dias_para_lotar))
    
    return {
        "alerta": True,
        "data_estimada_lotacao": data_prevista.strftime("%Y-%m-%d"),
        "taxa_geracao_diaria_kg": round(taxa_crescimento_diaria, 2)
    }