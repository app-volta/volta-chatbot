# VOLTA Chatbot IA

Chatbot corporativo para apoio à gestão de resíduos industriais, rastreabilidade operacional e indicadores ESG. O sistema foi desenhado para apoiar decisões de responsáveis técnicos; ele não substitui validação humana, procedimentos internos ou responsabilidade legal.

Este README descreve somente o componente de Inteligência Artificial do chatbot.

## Escopo

O chatbot recebe mensagens e imagens relacionadas à operação industrial e:

- classifica a intenção do usuário;
- analisa ocorrências de resíduos;
- consulta conhecimento técnico e regulatório com RAG;
- consulta métricas no PostgreSQL;
- avalia desempenho logístico de cooperativas;
- mantém histórico por sessão;
- retorna respostas corporativas com evidências, ressalvas e próximos passos.

O VOLTA não é marketplace, e-commerce nem aplicativo genérico de reciclagem.

## Arquitetura de IA

~~~mermaid
flowchart LR
    U[Usuário] --> API[FastAPI]
    API --> GI[Guardrail de entrada]
    GI --> R[Roteador]
    R --> T[Triagem]
    R --> N[Normas e FISPQs]
    R --> D[Dados e BI]
    R --> P[Performance]
    T --> SQL[(PostgreSQL)]
    D --> SQL
    P --> SQL
    SQL --> PR[Modelo preditivo]
    N --> RAG[(FAISS federado)]
    T --> J[Agente juiz]
    N --> J
    D --> J
    P --> J
    J --> O[Orquestrador]
    O --> GO[Guardrail de saída]
    GO --> API
    API <--> M[(MongoDB: sessões e checkpoints)]
~~~

### Fluxo de uma requisição

1. A API recebe session_id, usuário, tenant, mensagem e, opcionalmente, imagem.
2. O guardrail de entrada remove ou mapeia PII e bloqueia padrões de prompt injection.
3. O roteador escolhe uma única rota: triagem, normas, dados, performance ou fora_escopo.
4. O especialista executa suas ferramentas e devolve um resultado estruturado.
5. O agente juiz verifica consistência, evidências e aderência ao escopo.
6. O orquestrador transforma o JSON interno em uma resposta corporativa.
7. O guardrail de saída aplica a ressalva de validação humana e restaura PII somente na camada de apresentação.
8. A sessão e os checkpoints do LangGraph são persistidos no MongoDB.

## Agentes

| Agente | Responsabilidade | Recursos |
| --- | --- | --- |
| Roteador | Classificar intenção e encaminhar a mensagem original | Llama via Groq |
| Triagem | Interpretar relato ou imagem, sugerir categoria, risco e higienização | Gemini, inserir_nova_ocorrencia |
| Normas | Responder dúvidas técnicas, FISPQs, manuais, legislação e ODS 12 | Gemini, RAG federado |
| Dados e BI | Converter perguntas em consultas de métricas e históricos | Gemini, PostgreSQL |
| Performance | Avaliar SLA, tempo de resposta e engajamento logístico | Gemini, PostgreSQL |
| Juiz | Revisar o resultado do especialista e detectar afirmações sem suporte | Gemini |
| Orquestrador | Unificar formato, tom e próximos passos | Llama/Gemini |

O roteador não deve responder a casos de especialista. Ele apenas emite a decisão de rota e a pergunta original.

## Contratos estruturados

Os agentes se comunicam por objetos Pydantic, evitando dependência de texto livre:

- RouteDecision: rota escolhida, justificativa e pergunta original;
- SpecialistResult: análise de triagem, resumo de métricas, proposta de ocorrência e fontes;
- JudgeVerdict: aprovação ou reprovação da resposta e justificativa;
- CorporateAnswer: título, resposta final, ações recomendadas e fontes;
- ChatRequest: sessão, tenant, usuário, mensagem e imagem opcional.

Uma ocorrência criada pela IA é sempre uma proposta ou rascunho. O status inicial deve permanecer AGUARDANDO_VALIDACAO até a aprovação de um responsável.

## RAG federado

O módulo app/ai/multi_rag.py separa os contextos para reduzir mistura de fontes:

1. Operacional: manuais industriais, FISPQs, segregação e higienização.
2. Regulatório/ESG: legislação, políticas internas e ODS 12.
3. Cooperativas: contratos, regras de coleta e níveis de serviço.
4. Histórico: soluções e ocorrências já validadas.

Cada resultado deve preservar fonte, trecho, identificador do documento e metadados de validade. O agente de normas deve responder apenas com base no contexto recuperado; quando não houver evidência suficiente, deve declarar a limitação e solicitar validação.

A indexação esperada usa embeddings e FAISS. Os documentos reais não devem ser versionados no repositório quando contiverem informação interna ou sensível.

### Ingestao local

Coloque arquivos `.pdf`, `.txt` ou `.md` em um diretorio por corpus e execute:

```bash
python -m scripts.ingest_rag --corpus operational --directory data/documents/operational
```

Os indices FAISS e o manifesto de deduplicacao sao gravados em `data/faiss/<corpus>`. Os documentos fonte nao devem ser versionados quando contiverem dados internos.

## Modelo preditivo

O módulo app/ai/predictive.py complementa o fluxo generativo com uma previsão numérica determinística. A função prever_volume_futuro:

1. recebe o histórico diário de volume em quilogramas;
2. transforma as datas em uma série de dias decorridos;
3. calcula o volume acumulado;
4. treina uma regressão linear com scikit-learn;
5. projeta o volume acumulado para uma data futura;
6. retorna data projetada, taxa média diária e volume estimado.

Esse módulo é acionado por app/api/occurrences.py no endpoint /v1/occurrences/areas/{area_id}/predict_capacity. O histórico é obtido do PostgreSQL e exige pelo menos dois registros. A previsão serve como apoio à decisão logística e não substitui medição física da caçamba ou conferência operacional.

O retorno esperado contém sucesso, dias projetados, data projetada, taxa de geração diária em kg e volume estimado em kg. A capacidade máxima da área deve ser tratada como regra de negócio para calcular alerta de lotação; ela não deve ser confundida com a quantidade de dias da projeção.

### Atenção na integração atual

Na branch develop, o endpoint recebe capacidade_maxima, mas a chamada atual a repassa como o segundo argumento de prever_volume_futuro. Como a função interpreta esse argumento como dias_futuros, o contrato precisa ser ajustado antes de usar o alerta de lotação em produção. O ideal é separar explicitamente dias_futuros e capacidade_maxima e comparar o volume projetado com a capacidade da área.

Outro ponto de implantação: predictive.py importa pandas e scikit-learn, mas essas dependências precisam estar declaradas no requirements.txt para que uma instalação limpa da branch develop consiga iniciar a API.

## Memória e sessões

O MongoDB cumpre duas funções:

- histórico conversacional por session_id;
- checkpointer do LangGraph para retomar o estado do fluxo.

O identificador de sessão deve ser estável durante a conversa. O histórico enviado ao prompt deve ser limitado e sanitizado para evitar crescimento ilimitado de contexto. Dados transacionais, ocorrências e métricas continuam no PostgreSQL.

## Guardrails

### Entrada

- bloqueia tentativas conhecidas de prompt injection;
- anonimiza PII antes do processamento;
- mantém um mapa temporário para a camada autorizada de apresentação;
- rejeita mensagens fora do escopo industrial quando necessário.

### Saída

- impede que a IA se apresente como autoridade técnica absoluta;
- exige validação humana para segurança química, classificação e aprovação de ocorrência;
- evita expor PII ou detalhes internos indevidos;
- mantém resposta objetiva e corporativa.

Guardrails são controles de segurança, não substitutos para autenticação, autorização, auditoria ou revisão técnica.

## API do chatbot

A aplicação FastAPI expõe atualmente:

| Método | Rota | Finalidade |
| --- | --- | --- |
| GET | /health | Verificar disponibilidade |
| POST | /v1/sessions | Abrir uma sessão |
| GET | /v1/sessions/{session_id}/history | Recuperar histórico |
| POST | /v1/chat | Executar o fluxo multiagente |
| POST | /v1/occurrences/predict | Analisar imagem de resíduo |
| GET | /v1/occurrences/areas/{area_id}/predict_capacity | Prever volume futuro da área |
| GET | /v1/occurrences/reports/ai_summary | Preparar resumo gerencial de ocorrências |
| POST | /v1/occurrences/drafts | Criar rascunho de ocorrência |
| GET | /v1/occurrences/drafts | Listar rascunhos |
| POST | /v1/occurrences/drafts/{id}/approve | Aprovar ocorrência |

Exemplo de sessão:

~~~bash
curl -X POST http://localhost:8000/v1/sessions ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"demo-001\"}"
~~~

Exemplo de conversa:

~~~bash
curl -X POST http://localhost:8000/v1/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"demo-001\",\"tenant_id\":\"jbs-demo\",\"user_id\":\"operador-01\",\"message\":\"Como devo tratar um plástico multicamada contaminado?\"}"
~~~

## Estrutura do código de IA

~~~text
volta-chatbot/
├── app/
│   ├── ai/
│   │   ├── agents.py          # especialistas e ferramentas
│   │   ├── graph.py           # grafo LangGraph
│   │   ├── multi_rag.py       # retrievers FAISS
│   │   ├── predictive.py      # previsão de volume e capacidade
│   │   ├── prompts.py         # prompts dos agentes
│   │   ├── integrations.py    # modelos e integrações externas
│   │   └── mcp_server.py      # exposição de tools via MCP
│   ├── api/
│   │   ├── chat.py            # endpoint do chatbot
│   │   ├── sessions.py        # sessões e histórico
│   │   └── occurrences.py     # triagem e aprovação
│   ├── core/
│   │   ├── guardrails.py      # entrada e saída
│   │   ├── observability.py   # métricas e rastreamento
│   │   └── config.py          # configurações
│   └── db/
│       ├── storage.py         # PostgreSQL e MongoDB
│       └── models.py          # contratos Pydantic
├── client.py                  # cliente e cenários de teste
├── tests/
├── db/init.sql
├── docker-compose.yml
└── requirements.txt
~~~

## Execução local

1. Crie um arquivo .env com as credenciais e URLs dos serviços.
2. Suba as dependências:

~~~bash
docker compose up -d postgres mongo mongo-init
~~~

3. Instale as dependências:

~~~bash
python -m pip install -r requirements.txt
~~~

4. Inicie a API:

~~~bash
uvicorn app.main:app --reload
~~~

5. Abra a documentação interativa em http://localhost:8000/docs.

Variáveis principais:

~~~env
POSTGRES_DSN=postgresql://volta:volta@localhost:5432/volta
MONGO_URI=mongodb://localhost:27017/volta_memory
GROQ_API_KEY=
GEMINI_API_KEY=
~~~

O Neon e o PostgreSQL oficial do projeto. O PostgreSQL do Docker e opcional para testes locais e usa o mesmo schema definido em `db/init.sql`.

Nunca versione chaves, tokens, credenciais ou documentos internos.

## Observabilidade

O módulo de observabilidade deve registrar, por requisição e por agente:

- quantidade de chamadas;
- latência por etapa e tempo total;
- erros por rota;
- tokens de entrada e saída;
- custo estimado;
- custo por resolução;
- taxa de fallback, reprovação do juiz e intervenção humana.

Os dados devem permitir acompanhar cenários de 100 a 1.000 usuários semanais sem registrar conteúdo sensível em logs.

### Endpoints de observabilidade

- `GET /metrics`: formato Prometheus para coleta de latência, chamadas, erros, custos, fallbacks e resultados do juiz.
- `GET /v1/observability/summary?active_users=100&requests_per_user=5`: KPIs observados e projeção semanal de custo, ROI e custo por resolução.

O resumo aceita de 100 a 1.000 usuários semanais. Nenhum endpoint de observabilidade retorna o conteúdo das mensagens ou dados pessoais.

## Testes recomendados

O cliente e os testes devem cobrir, no mínimo:

- saudação e mensagem fora do escopo;
- roteamento para cada especialista;
- prompt injection e PII;
- consulta RAG sem evidência suficiente;
- geração de SQL somente leitura;
- triagem com e sem imagem;
- reprovação pelo agente juiz;
- retomada de uma sessão no MongoDB;
- falha de PostgreSQL, MongoDB ou provedor de modelo;
- resposta com ressalva de validação humana.

## Limitações atuais

- A qualidade do RAG depende da ingestão e atualização dos documentos oficiais.
- A análise de imagem é uma sugestão probabilística; não mede massa nem substitui inspeção.
- O chatbot não concede certificação química, ambiental ou regulatória.
- Toda alteração definitiva em ocorrência deve passar pelo fluxo de aprovação humana.
- Integrações externas precisam de timeout, retry controlado, logs sem PII e tratamento de indisponibilidade.
- O código deve ser executado com imports de pacote consistentes e contratos alinhados entre API, agentes e persistência.

## Princípio de responsabilidade

O VOLTA apoia a decisão operacional. A decisão final, a aprovação de ocorrência e a responsabilidade técnica permanecem com profissionais autorizados pela organização.
