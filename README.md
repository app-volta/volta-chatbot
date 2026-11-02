# VOLTA Chatbot IA

Chatbot corporativo para apoio à gestão de resíduos industriais, rastreabilidade operacional e indicadores ESG. O sistema foi desenhado para apoiar decisões de responsáveis técnicos; ele não substitui validação humana, procedimentos internos ou responsabilidade legal.

Este README descreve somente o componente de Inteligência Artificial do chatbot.

## Escopo

A aplicação oferece endpoints textuais e visuais para a operação industrial:

- classifica a intenção das mensagens de chat;
- analisa imagens de resíduos em endpoint separado;
- consulta conhecimento técnico e regulatório com RAG;
- consulta métricas no PostgreSQL;
- avalia desempenho logístico de cooperativas;
- mantém histórico por sessão;
- retorna respostas corporativas com evidências, ressalvas e próximos passos.

O VOLTA não é marketplace, e-commerce nem aplicativo genérico de reciclagem.

## Arquitetura de IA

~~~mermaid
flowchart LR
    U[Usuário no web ou mobile] --> API[FastAPI do chatbot]
    API --> CHAT[Chat: LangGraph]
    CHAT --> GI[Guardrail de entrada]
    GI --> R[Roteador]
    GI -->|bloqueado| B[Resposta de bloqueio]
    R --> T[Triagem]
    R --> N[Normas]
    R --> D[Dados]
    R --> P[Performance]
    R -->|resposta direta| O[Orquestrador]
    R -->|bloqueado| B
    T & N & D & P --> J[Juiz]
    J --> O
    O & B --> GO[Guardrail de saída]
    GO --> API
    API --> V[Análise visual de ocorrência]
    V --> VP[Triagem visual Gemini]
    VP --> CALC[Cálculo opcional: fatores EPA]
    CALC --> VJ[Juiz visual Gemini]
    VJ --> VS[Guardrail e assinatura]
    VS --> API
    RAG[(Qdrant ou FAISS: RAG)] -. contexto .-> T & N & D & P
    RAG -. corpus de peso, quando indexado .-> V
    N -. consulta .-> MCP[MCP de normas] --> MMA[Catálogo público do MMA]
    D & P -. consultas .-> SQL[(PostgreSQL)]
    API -. identidade .-> SQL
    API <--> M[(MongoDB: sessões e checkpoints)]
    M -. resumo ao encerrar sessão .-> RAG
    CHAT -. tracing opcional e sanitizado .-> LS[LangSmith]
~~~

O fluxo visual é separado do grafo textual. As rotas direta e bloqueada não passam pelos especialistas e pelo juiz. O RAG de peso depende da ingestão prévia das fontes; os trechos recuperados são contexto, não fatores numéricos automáticos. A validação humana permanece uma responsabilidade operacional, não uma etapa automática do diagrama. O modelo de previsão de capacidade é exposto por um endpoint separado e não faz parte do grafo do chat.

### Fluxo de uma requisição

1. A API de chat recebe `session_id` e mensagem de texto; imagens usam `/v1/occurrences/predict`. O usuário é identificado pelo JWT validado e a empresa é consultada no PostgreSQL.
2. O guardrail de entrada mascara padrões de dados pessoais conhecidos e bloqueia padrões conhecidos de prompt injection.
3. O roteador escolhe uma rota: triagem, normas, dados, performance, resposta direta ou bloqueio.
4. Nas rotas de especialistas, o agente executa suas ferramentas e devolve um resultado estruturado; as rotas direta e bloqueada seguem sem especialista e juiz.
5. Nas rotas de especialistas, o juiz avalia consistência, evidências e aderência ao escopo.
6. O orquestrador organiza a resposta nas rotas de especialistas e na rota direta; bloqueios seguem diretamente à saída.
7. O guardrail de saída mascara padrões conhecidos de dados pessoais e acrescenta a ressalva quando `requires_human_validation` está ativo. A rota `triage` sempre ativa o sinalizador; `direct` e `blocked` não o ativam. Em `standards`, o sinalizador vem da resposta; em `data` e `performance`, considera também a decisão do juiz.
8. A sessão e os checkpoints do LangGraph são persistidos no MongoDB.

## Agentes

| Agente | Responsabilidade | Recursos |
| --- | --- | --- |
| Roteador | Classificar intenção e encaminhar a mensagem original | Groq, com Gemini como alternativa configurável |
| Triagem | Analisar relato textual e sugerir categoria, risco e higienização | Modelo especialista, RAG operacional |
| Normas e documentação | Responder dúvidas explicativas sobre resíduos, funcionamento do VOLTA, FISPQs, manuais, legislação e ODS 12 | Modelo especialista, RAG federado, MCP do catálogo do MMA |
| Dados e BI | Converter perguntas em consultas de métricas e históricos | Modelo especialista, PostgreSQL |
| Performance | Avaliar conclusão das coletas e tempo de resposta | Modelo especialista, PostgreSQL |
| Juiz | Revisar o resultado do especialista e detectar afirmações sem suporte | Modelo especialista |
| Orquestrador | Unificar formato, tom e próximos passos | Groq ou Gemini, conforme configuração |

O modelo especialista usa Gemini como principal e pode usar Groq como alternativa quando configurado. O roteador emite a decisão de rota. A triagem de texto usa RAG operacional; a análise visual passa por endpoint separado, juiz e guardrails.

## Contratos estruturados

Os agentes se comunicam por objetos Pydantic, evitando dependência de texto livre:

- RouteDecision: rota escolhida, justificativa e resposta direta opcional;
- SpecialistResult: análise de triagem, resumo de métricas e proposta de ocorrência;
- JudgeVerdict: aprovação ou reprovação da resposta e justificativa;
- CorporateAnswer: título, resposta final, ações recomendadas e indicador de validação humana; as citações são retornadas separadamente no ChatResponse;
- ChatRequest: sessão e mensagem de texto; usuário e empresa vêm do JWT validado. A imagem é enviada em `/v1/occurrences/predict`.

Uma ocorrência criada pela IA é sempre uma proposta ou rascunho. O status inicial deve permanecer AGUARDANDO_VALIDACAO até a aprovação de um responsável.

## RAG federado

O módulo app/ai/multi_rag.py separa os contextos para reduzir mistura de fontes:

1. Operacional: manuais industriais, FISPQs, segregação e higienização.
2. Regulatório/ESG: legislação, políticas internas e ODS 12.
3. Cooperativas: contratos, regras de coleta e níveis de serviço.
4. Histórico: resumos privados de conversas do próprio usuário; não são fontes normativas nem ocorrências validadas.
5. Peso: referências de conversão de volume em massa para apoiar a análise visual, quando indexadas.

Os metadados de origem e os trechos são mantidos para fundamentar e avaliar as respostas. Para o PDF interno `volta.pdf`, esses metadados não são enviados aos agentes nem retornados nas citações da API; somente o conteúdo recuperado pode fundamentar a resposta ao cliente. Citações de outras fontes continuam sujeitas ao contrato normal da API. Perguntas explicativas sobre documentação e funcionamento do VOLTA usam a rota `standards`; relatos de ocorrências concretas usam `triage`. O agente de Normas e Documentação usa as evidências do RAG e pode pesquisar legislação externa pelo MCP; quando não houver evidência suficiente, deve declarar a limitação e solicitar validação.

O RAG usa Qdrant quando configurado; FAISS local é uma opção para desenvolvimento. No início da aplicação, os corpora estáticos `operational`, `regulatory` e `cooperatives` são verificados: coleções/índices ausentes ou vazios geram avisos no log, sem registrar credenciais ou conteúdo. Coleções ausentes continuam retornando nenhuma fonte; o aviso torna essa condição visível, mas não substitui a conferência de ingestão no ambiente. Memórias de conversa exigem correspondência de empresa e usuário; os demais corpora são referências compartilhadas. Documentos reais com informação interna ou sensível não devem ser versionados.

Em QA e produção, configure `QDRANT_URL` e, quando o cluster exigir autenticação, `QDRANT_API_KEY` nos secrets do ambiente. A ingestão usa `python -m scripts.ingest_rag --corpus <corpus> --directory <diretório>` e deve ser validada com recuperação de conteúdo após a carga. Não empacotamos FAISS nem o manual privado na imagem pública.

O manual interno VOLTA foi removido da árvore atual e não entra em novas imagens Docker. O blob ainda pode ser acessado em commits anteriores enquanto o repositório permanecer público; esta alteração não reescreve o histórico. Para indexá-lo localmente, obtenha a cópia autorizada e coloque-a em `data/documents/operational/volta.pdf` (caminho ignorado pelo Git), depois execute a ingestão abaixo para o backend de destino. Em produção, os pontos operacionais devem estar no Qdrant; a imagem não contém o PDF. O conteúdo pode fundamentar respostas, mas nome, páginas, trechos, IDs e links do manual não são retornados nas citações públicas. Ele não substitui FISPQs ou normas técnicas.

### Ingestao local

Para disponibilizar as referências públicas da EPA e de Minnesota à análise visual, configure o ambiente de destino e execute `python -m scripts.ingest_weight_references`. O comando baixa os dois PDFs oficiais e indexa suas páginas no corpus `weight`, preservando fonte e página. Execute-o apenas no ambiente desejado e verifique a recuperação após a ingestão. O endpoint visual consulta esse corpus antes de chamar o modelo, com uma busca geral; se estiver indisponível, continua sem as referências. Os trechos são apenas contexto: a extração de tabelas pode separar valores das unidades. O RAG não comprova o volume nem o conteúdo da foto, e os fatores experimentais fixos continuam restritos às condições explicitamente previstas.

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

O módulo app/ai/predictive.py aplica regressão linear à geração histórica registrada e retorna taxa média e projeção para o endpoint `/v1/occurrences/areas/{area_id}/predict_capacity`. O cálculo não subtrai coletas: o schema não informa o peso efetivamente coletado por ocorrência. Por compatibilidade, `volume_atual_kg` significa volume total histórico, não estoque físico. Os campos de lotação retornam `null` e explicam que o saldo não pode ser calculado. O histórico é limitado à empresa do usuário autenticado.
## Memória e sessões

O MongoDB guarda o histórico conversacional e o estado do LangGraph. Sessões são vinculadas à empresa e ao usuário; o histórico enviado ao prompt é limitado e sanitizado, e o estado calculado em cada turno é limpo antes do próximo. Resumos indexados no Qdrant são memórias privadas não validadas, filtradas por empresa e usuário; resumos legados sem `user_id` ficam inacessíveis até reindexação.

## Guardrails

### Entrada

- bloqueia tentativas conhecidas de prompt injection;
- mascara padrões conhecidos de dados pessoais antes do processamento;
- mantém um mapa temporário para a camada autorizada de apresentação;
- o roteador e os prompts orientam o tratamento de mensagens fora do escopo.

### Saída

- atenua padrões conhecidos de afirmações absolutas;
- ativa `requires_human_validation` em triagem; em `standards`, usa a resposta do modelo, e em `data` e `performance` considera também o resultado do juiz;
- mantém `requires_human_validation` falso nas rotas `direct` e `blocked`; o prompt orienta o modelo a manter o sinalizador falso para explicações gerais, saudações e redirecionamentos;
- mascara padrões conhecidos de dados pessoais na resposta;
- orienta respostas objetivas e apropriadas ao contexto.

Guardrails são controles de segurança, não substitutos para autenticação, autorização, auditoria ou revisão técnica.

## API do chatbot

A aplicação FastAPI expõe atualmente:

| Método | Rota | Finalidade |
| --- | --- | --- |
| GET | /health/live | Liveness do processo, sem dependência de banco |
| GET | /health/ready | Readiness do PostgreSQL e MongoDB (503 se degradado) |
| GET | /health | Alias de readiness |
| POST | /v1/sessions | Abrir uma sessão |
| GET | /v1/sessions/{session_id}/history | Recuperar histórico |
| POST | /v1/sessions/{session_id}/close | Encerrar sessão e, quando houver mensagens, tentar indexar resumo privado |
| POST | /v1/chat | Executar o fluxo multiagente |
| POST | /v1/occurrences/predict | Analisar imagem de resíduo |
| GET | /v1/occurrences/areas/{area_id}/predict_capacity | Prever volume futuro da área |
| GET | /v1/occurrences/reports/ai_summary | Preparar resumo gerencial de ocorrências |
| POST | /v1/occurrences/drafts | Criar rascunho de ocorrência |
| GET | /v1/occurrences/drafts | Listar rascunhos |
| POST | /v1/occurrences/drafts/{id}/approve | Aprovar ocorrência |
| GET | /v1/observability/summary | Resumo operacional e estimativas |
| POST | /v1/observability/resolutions | Registrar resolução operacional confirmada |
| GET | /metrics | Métricas operacionais para coleta externa |

Exemplo de sessão:

~~~bash
curl -X POST http://localhost:8000/v1/sessions \
  -H "Authorization: Bearer <jwt-da-volta-api>"
~~~

Exemplo de conversa:

~~~bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Authorization: Bearer <jwt-da-volta-api>" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<id-retornado-na-criacao-da-sessao>","message":"Como devo tratar um plástico multicamada contaminado?"}'
~~~

Em `POST /v1/chat`, `response.requires_human_validation` informa se a resposta demanda validação humana. As citações do PDF interno `volta.pdf` são omitidas da resposta pública; seu conteúdo continua sendo usado para fundamentar o texto. Citações de fontes externas ou de outros corpora podem ser retornadas normalmente.

Todas as rotas de negócio exigem `Authorization: Bearer <jwt-da-volta-api>`. O chatbot valida a assinatura e a expiração do JWT emitido pela `volta-api`, usa o e-mail do `sub` para buscar os UUIDs atuais em `users.id` e `users.company_id`, e deriva deles o usuário e a empresa. `tenant_id`, `user_id` e `company_id` enviados pelo cliente não definem o escopo autorizado. Configure `JWT_KEY` no secret `chatbot-secrets` com o mesmo valor usado pela `volta-api`; nunca versione essa chave.

## Configuração local e dependências

Use `.env.example` como catálogo de variáveis. `GEMINI_API_KEY` é necessária para embeddings e RAG; sem ela a aplicação interrompe o startup com motivo explícito. `GROQ_API_KEY` é opcional quando Gemini estiver configurado. QA e produção também precisam dos secrets de banco, JWT e Qdrant descritos no exemplo. LangSmith é opcional e só exporta traces quando `VOLTA_LANGSMITH_ENABLED=true`.

`requirements.txt` é o lock de produção para Python 3.12; `requirements.in` contém as faixas-fonte. `requirements-dev.txt` fixa pytest e Ruff para desenvolvimento/CI. Dependências de teste não são instaladas na imagem. Para atualizar os locks, use `uv pip compile requirements.in --output-file requirements.txt --python-version 3.12 --universal --generate-hashes` e o mesmo comando com `requirements-dev.in` e `requirements-dev.txt`. `pandas` e `scikit-learn` permanecem porque o modelo preditivo importa essas bibliotecas; o uso real de memória deve ser medido no cluster antes de ajustar os limites de 1 GiB.

O CI instala `requirements-dev.txt`, roda `ruff check . --select E4,E7,E9,F`, importa a aplicação e executa pytest. O lint cobre erros de sintaxe, nomes não definidos e imports básicos; regras estilísticas mais amplas ficam fora do gate para não transformar esta entrega em uma reformatação geral. O build publica `qa-<sha>` ao receber push em `develop` e `prod-<sha>` em `main`, notificando o DevOps com o secret `DEVOPS_DISPATCH_TOKEN`; o workflow manual só publica QA. O job de deploy do DevOps usa o Environment `prod`, que deve manter aprovação manual configurada. CORS aceita somente origens explícitas; `CORS_ORIGINS=*` é rejeitado porque credenciais estão habilitadas. Os métodos continuam em GET/POST: as rotas atuais não expõem DELETE de sessão.

## Estrutura do código de IA

~~~text
volta-chatbot/
├── app/
│   ├── ai/
│   │   ├── agents.py          # especialistas e ferramentas
│   │   ├── graph.py           # grafo LangGraph
│   │   ├── multi_rag.py       # retrievers Qdrant ou FAISS
│   │   ├── predictive.py      # previsão de geração registrada
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

1. Copie `.env.example` para `.env` e substitua os placeholders localmente; não versione `.env`.
2. Use Python 3.12 e instale as dependências de runtime e desenvolvimento:

~~~bash
python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt
~~~

3. Inicie a API:

~~~bash
uvicorn app.main:app --reload
~~~

4. Abra a documentação interativa em http://localhost:8000/docs.

Para o exemplo de MongoDB local, configure um replica set chamado `rs0`, necessário para os checkpoints. Use o ID retornado pela criação da sessão no exemplo de conversa; os comandos `curl` acima usam sintaxe de shell Bash.

Variáveis principais:

~~~env
POSTGRES_DSN=postgresql://volta:volta@localhost:5432/volta
MONGO_URI=mongodb://localhost:27017/volta_memory?replicaSet=rs0
JWT_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=
OBSERVABILITY_API_KEY=
~~~

`OBSERVABILITY_API_KEY` é um segredo aleatório apenas para operadores. Use `Authorization: Bearer <OBSERVABILITY_API_KEY>` nas rotas `/v1/observability/*` e em `/metrics`. Sem a chave, esses endpoints retornam 503; chave inválida retorna 401. O JWT dos clientes não concede acesso à observabilidade global.

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

- `GET /metrics`: métricas operacionais de latência, chamadas, erros, custos, fallbacks e resultados do juiz.
- `GET /v1/observability/summary?active_users=100&requests_per_user=5`: resumo autenticado de mensagens do chat, latência média, taxa de erro por mensagem e projeção semanal de custo estimado.

O resumo aceita de 100 a 1.000 usuários semanais. Nenhum endpoint de observabilidade retorna o conteúdo das mensagens ou dados pessoais.

### SCRUM-1955 — primeira etapa de observabilidade do chat

Cada mensagem acumula as estimativas dos agentes dentro de um contexto próprio,
inclusive quando o trabalho passa para threads AnyIO/LangGraph. O custo médio
divide esse total pelo número de mensagens finalizadas (sucessos, bloqueios,
negações de acesso e erros), não pelo número de agentes. Chamadas de imagem e relatório gerencial também registram uso e custo por
agente, mas não entram na projeção semanal de mensagens do chat. Os logs de conclusão contêm
rota, status, duração e custo estimado, correlacionados pelo `request_id` já
existente, sem conteúdo de conversa.

Limites desta etapa:

- Tokens usam metadados do provedor quando disponíveis; chamadas sem esses
  metadados usam estimativa por caracteres/4. Custos usam preços configurados,
  não incluem integralmente retries ou embeddings e não representam a fatura.
- Sem amostra de mensagens, custo, latência e taxa de erro retornam `null`.
- Aprovação do juiz e necessidade de validação humana são eventos separados;
  não comprovam resolução operacional. Custo por resolução e valor/ROI ficam
  `null` até existir uma confirmação operacional mensurável.
- `fallback_rate` fica `null` quando não há reporte explícito do fallback.
- Agentes no resumo incluem outras rotas de IA; o bloco de mensagens/projeções
  cobre apenas o chat. Rejeições de autenticação e payload anteriores ao handler
  não entram nessa amostra.
- Os contadores residem no processo e reiniciam com ele. O histórico exige coleta
  externa; o resumo não agrega réplicas nem isola empresas.
  É uma visão operacional interna, não um painel para clientes.

A resolução é informada em `/v1/observability/resolutions` com `request_id` e
`resolved`. O feedback fica em memória, limita-se às 10.000 requisições mais
recentes e se perde ao reiniciar o processo.

O histórico das métricas depende de coleta e armazenamento externos; sua configuração
deve ser verificada no ambiente.
O aplicativo mobile continua consumindo os endpoints de chat normalmente.

### SCRUM-1964 — rastreamento do chat no LangSmith

O LangSmith complementa as métricas locais com a árvore de execução do grafo e
das chamadas de modelos. A integração é opcional e vem desligada. Não muda o
contrato do mobile nem cria um novo endpoint de gastos. O endpoint `summary`
continua calculando as métricas locais; ele não consulta o LangSmith.

Configuração de QA (variáveis no container do chatbot):

~~~env
VOLTA_LANGSMITH_ENABLED=true
LANGSMITH_PROJECT=volta-chatbot-qa
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
~~~

Cadastre `LANGSMITH_API_KEY` no Secret do Kubernetes consumido pelo chatbot,
sem substituir as outras chaves existentes. A chave não deve ir ao Git, ao
mobile ou ao chat. Se a chave exigir um workspace, configure também
`LANGSMITH_WORKSPACE_ID`. Use o endpoint da região da conta LangSmith.

Use `VOLTA_LANGSMITH_ENABLED`, não o interruptor global `LANGSMITH_TRACING`:
o envio é explícito, limitado ao grafo do chat e usa um cliente com filtro de
privacidade. O middleware desativa o rastreamento automático durante as
requisições para evitar um segundo envio sem esse filtro.

Antes de enviar cada criação/atualização de span, o filtro remove entradas,
saídas, configuração serializada, eventos, tags, dados de runtime e detalhes
de erros. Metadados ficam limitados à identificação da requisição, ambiente,
modelo/provedor e contagens de tokens. Não são exportados histórico, PDF,
identificadores de empresa/usuário ou `thread_id` da sessão do chatbot.
Nomes de etapas conhecidos são mantidos; nomes desconhecidos viram o tipo do
span. O `request_id` permite correlacionar a execução aos logs operacionais.

Tokens são extraídos de `usage_metadata` das respostas dos modelos antes de
remover o conteúdo. Quando faltam, o span recebe `usage_missing=true`; ausência
não significa custo zero. O LangSmith estima o custo pelos preços dos modelos
que reconhecer. Isso não inclui a conta AWS nem comprova resolução operacional
ou qualidade da resposta. Métricas locais continuam com seus limites descritos
acima; os limites didáticos de p95 de 8 s e erro de 5% não são um SLA do VOLTA.

Envio ocorre em segundo plano e o cliente solicita o descarregamento do buffer
no encerramento. A entrega é best effort: uma interrupção abrupta ou falha de
rede pode perder traces; não é uma trilha de auditoria durável.
Sem chave ou com falha na inicialização, a integração permanece desligada;
indisponibilidade do observador não deve impedir o atendimento do chat.
Imagem, relatório e resumo de encerramento de sessão não são instrumentados
por esta etapa. Bloqueios anteriores ao grafo continuam nas métricas locais.

Aceitação em QA após publicar a alteração: enviar uma mensagem sintética,
conferir grafo e chamadas filhas no projeto `volta-chatbot-qa`, comparar tokens
com o provedor e inspecionar também um erro e uma chamada de ferramenta.
Confirmar ausência de conteúdo em todos os spans e verificar que o chat atende
com a integração desligada ou com LangSmith indisponível. A criação do projeto e
da chave, por si só, não comprova essa aceitação.

Validação local da integração: `python -m pytest -q tests/test_langsmith_tracing.py
tests/test_chat.py tests/test_model_usage.py tests/test_observability.py
tests/test_config.py` passou com 30 testes em Python 3.14. Os testes novos usam
modelo sintético e capturam as operações no limite de envio do SDK, sem chave
real nem chamadas externas. Verificam privacidade, tokens, herança do callback
nas chamadas filhas e compatibilidade com métricas locais. Não substituem a
aceitação com LangGraph, bancos e provedores reais em QA.

## Testes recomendados

O cliente e os testes devem cobrir, no mínimo:

- saudação e mensagem fora do escopo;
- roteamento para cada especialista;
- prompt injection e PII;
- consulta RAG sem evidência suficiente;
- consultas de dados somente leitura;
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
- Rascunhos de ocorrência criados pelo chatbot seguem o fluxo de aprovação humana; outras alterações dependem das regras da API de negócio.
- Integrações externas precisam de timeout, retry controlado, logs sem PII e tratamento de indisponibilidade.
- O código deve ser executado com imports de pacote consistentes e contratos alinhados entre API, agentes e persistência.

## Princípio de responsabilidade

O VOLTA apoia a decisão operacional. A decisão final, a aprovação de ocorrência e a responsabilidade técnica permanecem com profissionais autorizados pela organização.
