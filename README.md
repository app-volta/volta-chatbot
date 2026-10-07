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
    U[Usuário] --> API[FastAPI]
    API --> GI[Guardrail de entrada]
    GI --> R[Roteador]
    R --> T[Triagem]
    R --> N[Normas e FISPQs]
    R --> D[Dados e BI]
    R --> P[Performance]
    T --> RAG[(Qdrant ou FAISS federado)]
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

1. A API de chat recebe session_id e mensagem de texto; imagens usam `/v1/occurrences/predict`. Usuário e tenant vêm do JWT validado.
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
| Triagem | Analisar relato textual e sugerir categoria, risco e higienização | Gemini, RAG operacional |
| Normas e documentação | Responder dúvidas explicativas sobre resíduos, funcionamento do VOLTA, FISPQs, manuais, legislação e ODS 12 | Gemini, RAG federado, MCP do catálogo do MMA |
| Dados e BI | Converter perguntas em consultas de métricas e históricos | Gemini, PostgreSQL |
| Performance | Avaliar conclusão das coletas e tempo de resposta | Gemini, PostgreSQL |
| Juiz | Revisar o resultado do especialista e detectar afirmações sem suporte | Gemini |
| Orquestrador | Unificar formato, tom e próximos passos | Llama/Gemini |

O roteador emite a decisão de rota. A triagem de texto usa RAG operacional; a análise visual passa por endpoint separado, juiz e guardrails.

## Contratos estruturados

Os agentes se comunicam por objetos Pydantic, evitando dependência de texto livre:

- RouteDecision: rota escolhida, justificativa e pergunta original;
- SpecialistResult: análise de triagem, resumo de métricas, proposta de ocorrência e fontes;
- JudgeVerdict: aprovação ou reprovação da resposta e justificativa;
- CorporateAnswer: título, resposta final, ações recomendadas e fontes;
- ChatRequest: sessão e mensagem de texto; usuário e empresa vêm do JWT validado. A imagem é enviada em `/v1/occurrences/predict`.

Uma ocorrência criada pela IA é sempre uma proposta ou rascunho. O status inicial deve permanecer AGUARDANDO_VALIDACAO até a aprovação de um responsável.

## RAG federado

O módulo app/ai/multi_rag.py separa os contextos para reduzir mistura de fontes:

1. Operacional: manuais industriais, FISPQs, segregação e higienização.
2. Regulatório/ESG: legislação, políticas internas e ODS 12.
3. Cooperativas: contratos, regras de coleta e níveis de serviço.
4. Histórico: resumos privados de conversas do próprio usuário; não são fontes normativas nem ocorrências validadas.

Os metadados de origem e os trechos são mantidos para fundamentar e avaliar as respostas. Para o PDF interno `volta.pdf`, esses metadados não são enviados aos agentes nem retornados nas citações da API; somente o conteúdo recuperado pode fundamentar a resposta ao cliente. Citações de outras fontes continuam sujeitas ao contrato normal da API. Perguntas explicativas sobre documentação e funcionamento do VOLTA usam a rota `standards`; relatos de ocorrências concretas usam `triage`. O agente de Normas e Documentação usa as evidências do RAG e pode pesquisar legislação externa pelo MCP; quando não houver evidência suficiente, deve declarar a limitação e solicitar validação.

A indexação usa embeddings e, com `QDRANT_URL`, Qdrant para os quatro corpora; sem a URL, usa FAISS local. Memórias de conversa exigem correspondência de empresa e usuário; os demais corpora são referências compartilhadas. Documentos reais com informação interna ou sensível não devem ser versionados.

O manual interno VOLTA foi removido da árvore atual e não entra em novas imagens Docker. O blob ainda pode ser acessado em commits anteriores enquanto o repositório permanecer público; esta alteração não reescreve o histórico. Para indexá-lo localmente, obtenha a cópia autorizada e coloque-a em `data/documents/operational/volta.pdf` (caminho ignorado pelo Git), depois execute a ingestão abaixo para o backend de destino. Em produção, os pontos operacionais devem estar no Qdrant; a imagem não contém o PDF. O conteúdo pode fundamentar respostas, mas nome, páginas, trechos, IDs e links do manual não são retornados nas citações públicas. Ele não substitui FISPQs ou normas técnicas.

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

O módulo app/ai/predictive.py aplica regressão linear à geração histórica registrada e retorna taxa média e projeção para o endpoint `/v1/occurrences/areas/{area_id}/predict_capacity`. O cálculo não subtrai coletas: o schema não informa o peso efetivamente coletado por ocorrência. Por compatibilidade, `volume_atual_kg` significa volume total histórico, não estoque físico. Os campos de lotação retornam `null` e explicam que o saldo não pode ser calculado. O histórico é limitado à empresa do usuário autenticado.
## Memória e sessões

O MongoDB guarda o histórico conversacional e o estado do LangGraph. Sessões são vinculadas à empresa e ao usuário; o histórico enviado ao prompt é limitado e sanitizado, e o estado calculado em cada turno é limpo antes do próximo. Resumos indexados no Qdrant são memórias privadas não validadas, filtradas por empresa e usuário; resumos legados sem `user_id` ficam inacessíveis até reindexação.

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
| GET | /health/live | Liveness do processo, sem dependência de banco |
| GET | /health/ready | Readiness do PostgreSQL e MongoDB (503 se degradado) |
| GET | /health | Alias de readiness |
| POST | /v1/sessions | Abrir uma sessão |
| GET | /v1/sessions/{session_id}/history | Recuperar histórico |
| POST | /v1/sessions/{session_id}/close | Encerrar sessão e indexar resumo privado |
| POST | /v1/chat | Executar o fluxo multiagente |
| POST | /v1/occurrences/predict | Analisar imagem de resíduo |
| GET | /v1/occurrences/areas/{area_id}/predict_capacity | Prever volume futuro da área |
| GET | /v1/occurrences/reports/ai_summary | Preparar resumo gerencial de ocorrências |
| POST | /v1/occurrences/drafts | Criar rascunho de ocorrência |
| GET | /v1/occurrences/drafts | Listar rascunhos |
| POST | /v1/occurrences/drafts/{id}/approve | Aprovar ocorrência |
| GET | /v1/observability/summary | Resumo operacional e estimativas |
| POST | /v1/observability/resolutions | Registrar resolução operacional confirmada |
| GET | /metrics | Métricas Prometheus |

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

- `GET /metrics`: formato Prometheus para coleta de latência, chamadas, erros, custos, fallbacks e resultados do juiz.
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
- Os contadores residem no processo e reiniciam com ele. `/metrics` exige coleta
  por Prometheus para histórico; resumo não agrega réplicas nem isola empresas.
  É uma visão operacional interna, não um painel para clientes.

A resolução é informada em `/v1/observability/resolutions` com `request_id` e
`resolved`. O feedback fica em memória, limita-se às 10.000 requisições mais
recentes e se perde ao reiniciar o processo.

Integração operacional: coletar `/metrics` na rede interna, montar painéis de
latência, erros, custos estimados, juiz e validação humana no Grafana. Essa
infraestrutura e a coleta persistente ainda não são provisionadas por esta mudança.
O aplicativo mobile continua consumindo os endpoints de chat normalmente.

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
