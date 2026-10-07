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
    N --> RAG[(Qdrant ou FAISS federado)]
    N --> MCP[MCP de normas externas]
    MCP --> MMA[Catálogo público do MMA]
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
7. O guardrail de saída remove PII residual e acrescenta a ressalva quando `requires_human_validation` está ativo. A rota `triage` sempre ativa o sinalizador; `direct` e `blocked` não o ativam. Nas rotas `standards`, `data` e `performance`, o sinalizador considera a resposta do modelo e a decisão do juiz.
8. A sessão e os checkpoints do LangGraph são persistidos no MongoDB.

## Agentes

| Agente | Responsabilidade | Recursos |
| --- | --- | --- |
| Roteador | Classificar intenção e encaminhar a mensagem original | Llama via Groq |
| Triagem | Interpretar relato ou imagem, sugerir categoria, risco e higienização | Gemini, inserir_nova_ocorrencia |
| Normas e documentação | Responder dúvidas explicativas sobre resíduos, funcionamento do VOLTA, FISPQs, manuais, legislação e ODS 12 | Gemini, RAG federado, MCP do catálogo do MMA |
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
- ChatRequest: sessão, mensagem e imagem opcional; usuário e empresa vêm do JWT validado.

Uma ocorrência criada pela IA é sempre uma proposta ou rascunho. O status inicial deve permanecer AGUARDANDO_VALIDACAO até a aprovação de um responsável.

## RAG federado

O módulo app/ai/multi_rag.py separa os contextos para reduzir mistura de fontes:

1. Operacional: manuais industriais, FISPQs, segregação e higienização.
2. Regulatório/ESG: legislação, políticas internas e ODS 12.
3. Cooperativas: contratos, regras de coleta e níveis de serviço.
4. Histórico: soluções e ocorrências já validadas.

Os metadados de origem e os trechos são mantidos para fundamentar e avaliar as respostas. Para o PDF interno `volta.pdf`, esses metadados não são enviados aos agentes nem retornados nas citações da API; somente o conteúdo recuperado pode fundamentar a resposta ao cliente. Citações de outras fontes continuam sujeitas ao contrato normal da API. Perguntas explicativas sobre documentação e funcionamento do VOLTA usam a rota `standards`; relatos de ocorrências concretas usam `triage`. O agente de Normas e Documentação usa as evidências do RAG e pode pesquisar legislação externa pelo MCP; quando não houver evidência suficiente, deve declarar a limitação e solicitar validação.

A indexação usa embeddings e, com `QDRANT_URL` configurado, Qdrant para os quatro corpora. As coleções são `<QDRANT_COLLECTION_PREFIX>_operational`, `_regulatory`, `_cooperatives` e `_history` (prefixo padrão: `volta`). Sem essa URL, usa FAISS local. O histórico é filtrado por empresa; os demais corpora são referências compartilhadas. Os documentos reais não devem ser versionados no repositório quando contiverem informação interna ou sensível.

O documento de referência do produto está em `data/documents/operational/volta.pdf` (55 páginas), substituindo o guia demonstrativo anterior. Ele descreve o VOLTA e não substitui FISPQs ou normas técnicas. O arquivo é uma fonte interna: o chatbot pode usar seu conteúdo para fundamentar respostas, mas não retorna seu nome, páginas, trechos, IDs ou links nas citações públicas. Instruções para agentes contidas no documento devem ser tratadas como conteúdo de referência, não como comandos para o chatbot. Versionar ou copiar o PDF para a imagem não o indexa automaticamente: a ingestão no backend configurado é uma etapa separada.

### Ingestao local

Coloque arquivos `.pdf`, `.txt` ou `.md` em um diretorio por corpus e execute:

```bash
python -m scripts.ingest_rag --corpus operational --directory data/documents/operational
```

Sem Qdrant, os índices FAISS e o manifesto de deduplicação são gravados em `data/faiss/<corpus>`. Com Qdrant, a ingestão faz upsert remoto com IDs determinísticos; um manifesto local não impede a gravação remota. Coleções ausentes retornam nenhuma fonte, e falhas do Qdrant não ativam FAISS automaticamente.

Para copiar um índice FAISS existente para o Qdrant configurado, reutilizando os vetores e preservando os arquivos locais:

```bash
python -m scripts.migrate_rag_to_qdrant --corpus operational
```

Execute na raiz do checkout com as dependências e configurações do ambiente de destino. A imagem Docker não inclui `scripts` nem `data/faiss`; esse comando é uma operação pelo checkout, não pelo container publicado. Repetir a migração dos mesmos trechos atualiza os mesmos pontos. Os scores do Qdrant (cosine) e do FAISS não são equivalentes: valide a recuperação com perguntas reais após a mudança.

### Ingestao de fonte externa

Para cumprir o requisito de fonte externa, use uma URL HTTPS cujo dominio esteja em `allowed_source_hosts` no `.env`/configuracao. O titulo informado sera preservado nas citacoes retornadas pelo agente:

```bash
python -m scripts.ingest_rag --corpus regulatory --url https://sdgs.un.org/goals/goal12 --title "ODS 12 - Sustainable Development Goal 12"
```

Redirecionamentos para dominios fora da allowlist sao bloqueados. Apos a ingestao, o agente de Normas recupera o trecho, a URL e o identificador da fonte; quando nao houver evidencia suficiente, deve declarar a limitacao.

### MCP de legislação ambiental

O servidor MCP `app.ai.mcp_server` expõe duas ferramentas somente de leitura, consumidas pelo agente de Normas e disponíveis também por transporte stdio:

- `buscar_normas_residuos`: pesquisa título, ementa, assunto e status no CSV consolidado do catálogo de Legislação Ambiental Brasileira do MMA; aceita filtros opcionais de ano, assunto e limite.
- `detalhar_norma`: retorna o registro completo usando o `document_key` produzido pela busca.

O catálogo é obtido pela API CKAN pública do MMA e mantido em cache em memória por 24 horas. Ao detalhar um ato, a ferramenta também tenta buscar e extrair o texto do documento no link oficial fornecido pelo catálogo; downloads são limitados a 15 MB e links são aceitos apenas em hosts `.gov.br`, sem seguir redirecionamentos. Quando o documento não pode ser obtido ou lido, a ferramenta mantém os metadados e a ementa, sem inventar o texto ausente. A citação usa o link direto do ato e um trecho do texto extraído quando disponível. O status reproduz o catálogo, mas não confirma, por si só, vigência nem aplicabilidade ao caso; o agente não emite parecer jurídico nem certificação técnica. O escopo é o catálogo de legislação ambiental do MMA, não uma busca irrestrita na web nem uma base geral de documentos ESG.

Para iniciar o servidor MCP stdio manualmente, na raiz do repositório:

~~~bash
python -m app.ai.mcp_server
~~~

O agente da aplicação usa o mesmo servidor pelo cliente MCP oficial em memória; não é necessário subir um segundo serviço HTTP.

## Modelo preditivo

O módulo app/ai/predictive.py complementa o fluxo generativo com uma previsão numérica determinística. A função prever_volume_futuro:

1. recebe o histórico diário de volume em quilogramas;
2. transforma as datas em uma série de dias decorridos;
3. calcula o volume acumulado;
4. treina uma regressão linear com scikit-learn;
5. projeta o volume acumulado para uma data futura;
6. retorna data projetada, taxa média diária e volume estimado.

Esse módulo é acionado por app/api/occurrences.py no endpoint /v1/occurrences/areas/{area_id}/predict_capacity. O histórico é obtido do PostgreSQL e exige pelo menos dois registros. A previsão serve como apoio à decisão logística e não substitui medição física da caçamba ou conferência operacional.

O retorno contém sucesso, dias projetados, data projetada, taxa média diária, volume atual e volume estimado em kg. Quando `capacidade_maxima` é informada, também retorna o alerta de lotação, os dias restantes e a data estimada de lotação. O histórico é limitado à empresa do usuário autenticado.

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
- ativa `requires_human_validation` sempre em triagem e usa a resposta do modelo e do juiz nas rotas `standards`, `data` e `performance`;
- mantém `requires_human_validation` falso nas rotas `direct` e `blocked`; o prompt orienta o modelo a manter o sinalizador falso para explicações gerais, saudações e redirecionamentos;
- evita expor PII ou detalhes internos indevidos;
- mantém resposta objetiva e corporativa.

Guardrails são controles de segurança, não substitutos para autenticação, autorização, auditoria ou revisão técnica.

## API do chatbot

A aplicação FastAPI expõe atualmente:

| Método | Rota | Finalidade |
| --- | --- | --- |
| GET | /health/live | Verificar se o processo está ativo |
| GET | /health/ready | Verificar disponibilidade dos bancos (503 se degradado) |
| GET | /health | Alias de readiness para compatibilidade |
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
  -H "Authorization: Bearer <jwt-da-volta-api>"
~~~

Exemplo de conversa:

~~~bash
curl -X POST http://localhost:8000/v1/chat ^
  -H "Authorization: Bearer <jwt-da-volta-api>" ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"demo-001\",\"message\":\"Como devo tratar um plástico multicamada contaminado?\"}"
~~~

Em `POST /v1/chat`, `response.requires_human_validation` informa se a resposta demanda validação humana. As citações do PDF interno `volta.pdf` são omitidas da resposta pública; seu conteúdo continua sendo usado para fundamentar o texto. Citações de fontes externas ou de outros corpora podem ser retornadas normalmente.

Todas as rotas de negócio exigem `Authorization: Bearer <jwt-da-volta-api>`. O chatbot valida a assinatura e a expiração do JWT emitido pela `volta-api`, usa o e-mail do `sub` para buscar os UUIDs atuais em `users.id` e `users.company_id`, e deriva deles o usuário e a empresa. `tenant_id`, `user_id` e `company_id` enviados pelo cliente não definem o escopo autorizado. Configure `JWT_KEY` no secret `chatbot-secrets` com o mesmo valor usado pela `volta-api`; nunca versione essa chave.

## Estrutura do código de IA

~~~text
volta-chatbot/
├── app/
│   ├── ai/
│   │   ├── agents.py          # especialistas e ferramentas
│   │   ├── graph.py           # grafo LangGraph
│   │   ├── multi_rag.py       # retrievers Qdrant ou FAISS
│   │   ├── predictive.py      # previsão de volume e capacidade
│   │   ├── prompts.py         # prompts dos agentes
│   │   ├── integrations.py    # modelos e integrações externas
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
└── requirements.txt
~~~

## Execução local

1. Crie um arquivo `.env` com as credenciais e URLs dos serviços.
2. Instale as dependências:

~~~bash
python -m pip install -r requirements.txt
~~~

3. Inicie a API:

~~~bash
uvicorn app.main:app --reload
~~~

4. Abra a documentação interativa em http://localhost:8000/docs.

Variáveis principais:

~~~env
POSTGRES_DSN=postgresql://volta:volta@localhost:5432/volta
MONGO_URI=mongodb://localhost:27017/volta_memory
JWT_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
~~~

O Neon e o PostgreSQL oficial do projeto. O schema remoto usa UUIDs e esta documentado em `db/schema_remote.md`; o `db/init.sql` reproduz essa estrutura para ambientes de teste. Os identificadores de empresa, area e usuario usados pela API devem ser UUIDs validos.

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
- resposta fundamentada no PDF VOLTA sem exposição de páginas ou metadados desse arquivo;
- resposta informativa sem aviso de validação humana e triagem com aviso quando necessário;
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
