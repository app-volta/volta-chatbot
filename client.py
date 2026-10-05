import requests
import os

BASE_URL = "http://127.0.0.1:8000"
TOKEN = os.getenv("VOLTA_JWT")

if not TOKEN:
    raise SystemExit("Defina VOLTA_JWT com um JWT válido emitido pela volta-api.")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

print("🤖 Iniciando o VOLTA Chat...")

# 1. Cria a sessão automaticamente
sessao_response = requests.post(f"{BASE_URL}/v1/sessions", headers=HEADERS)
sessao_response.raise_for_status()
sessao_id = sessao_response.json()["session_id"]
print(f"✅ Sessão criada! ID: {sessao_id}\n")
print("Digite 'sair' para encerrar.\n")
print("-" * 50)

# 2. O Loop Dinâmico de Perguntas e Respostas
while True:
    pergunta = input("\n👤 Você: ")
    
    if pergunta.lower() == 'sair':
        print("Até logo!")
        break
        
    payload = {
        "session_id": sessao_id,
        "message": pergunta
    }
    
    # 3. Envia para a API e espera a resposta
    resposta = requests.post(f"{BASE_URL}/v1/chat", headers=HEADERS, json=payload)
    
    if resposta.status_code == 200:
        dados = resposta.json()
        print(f"\n🧠 VOLTA (Rota: {dados['route']}):")
        print(f"💬 {dados['response']['answer']}")
    else:
        print(f"\n Erro na API: {resposta.status_code} - {resposta.text}")
