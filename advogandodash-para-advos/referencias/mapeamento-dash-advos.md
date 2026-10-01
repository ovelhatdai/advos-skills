# Mapeamento AdvogandoDash → AdvOS

Levantado em 30/09/2026, no conversor usado na migração de setembro e nos esquemas do MCP de importação
(`imports_schema`, versão 1). Antes de cada escritório, conferir o esquema atual: o produto muda.

## Ordem, chaves e namespace

- **Ordem de gravação:**
  1. cadastro (`crm`: `client`, `client_party`);
  2. jurídico (`legal`: `legal_case` → `proceeding`, `deadline`, `task`);
  3. documentos (`documents`: `client_document`).

  Contratos (`crm/deal`) e financeiro (`finance`) vêm depois, se o escritório decidir levar.
- **Chave de origem (`externalKey`):** o id do registro no Dash. Com ela, o `imports_lookup` confere o que entrou, e o
  reenvio não duplica.
- **Namespace: um por escritório,** no formato `advogandodash-<escritório>`. Nunca reutilizar o namespace de outro
  escritório.
- **Referências entre registros do mesmo lote:** `{"entity": "legal_case", "externalKey": "<id no Dash>"}`.
  **Referências a algo que já existe no AdvOS:** `{"id": "<id no AdvOS>"}`. Membros sempre pelo `userId`.

## Cliente (`crm/client`)

| Dash (`Cliente`) | AdvOS | Observação |
|---|---|---|
| `nome_completo` | `full_name` | obrigatório |
| `cpf` | `cpf` | Pessoa física exige CPF válido. Sem ele, o cliente não entra: corrigir no Dash. |
| `rg`, `data_nascimento`, `email`, `profissao` | `rg`, `date_of_birth`, `email`, `occupation` | Data de nascimento no futuro é recusada. |
| `telefone_1`…`telefone_4` | `phone_primary`, `phone_secondary` | Sem repetição. Do 3º em diante vão para `notes`. |
| `estado_civil` | `marital_status` | tabela fixa abaixo |
| `endereco_completo`, `cidade`, `estado`, `cep`, `bairro` | `full_address`, `city`, `state`, `zip_code`, `neighborhood` | |
| `canal_aquisicao` | `acquisition_channel` | tabela fixa. O que não estiver nela vira `other`. |
| `status_cliente` | `status` | tabela fixa |
| `data_contrato` | `contract_date` | |
| `vendedor_id` | `salesperson_id` (membro) | Por e-mail. Sem par, entra sem vendedor, com pendência. |
| `observacoes`, `resumo_caso` | `notes` | Tirar linhas com senha. O vídeo de confirmação entra como link. |
| `representante_legal_*` | `client_party` com `role: legal_representative` | nome, CPF, RG, parentesco |

O AdvOS também tem campos que o conversor de setembro não preenchia: `mother_name`, `father_name`, `pis_pasep`, `ctps`,
`benefit_number`, `address_number` e `address_complement`. Se o Dash do escritório tiver esses dados, mapear.

## Processo (`legal/legal_case`)

| Dash (`ProcessoJuridico`) | AdvOS | Observação |
|---|---|---|
| `tipo_processo` + `numero_processo` | `process_type`, `process_number` / `inss_protocol` | Judicial exige CNJ com 20 dígitos. No administrativo, o número vai em `inss_protocol`. |
| `status_fase_id` (catálogo) | `case_status_id` | ver "Catálogos" |
| `tipo_servico_id` (catálogo) | `legal_service_type_id` | ver "Catálogos" |
| `condicao_id` do cliente (catálogo) | `medical_condition_id` | ver "Catálogos" |
| `responsavel_id` | `assigned_to_id`, `responsible_user_id` (membro) | por e-mail |
| `processo_origem_id`, `relacao_processo_anterior`, `ordem_cronologica` | `origin_case_id`, `relation_type`, `chronological_order` | Cadeia de tentativas: ver armadilha 9 da gravação. |
| `comarca`, `juiz_nome`, `parte_contraria`, `vara_subsecao`, `secao_judiciaria`, `tribunal_estadual`, `assunto_cnj`, `tipo_acao`, `trf_id` | `comarca`, `judge_name`, `opposing_party`, `court_subsection`, `judicial_section`, `state_court`, `cnj_subject`, `action_type`, `trf` | `trf` só aceita de TRF1 a TRF6. |
| datas: protocolo, citação, contestação, perícia, sentença, recurso do INSS, julgamento do recurso, trânsito em julgado, conclusão | `filing_date`, `citation_date`, `contestation_date`, `expert_exam_date`, `first_instance_sentence_date`, `inss_appeal_date`, `appeal_judgment_date`, `final_judgment_date`, `closed_at` | |
| `resumo_caso`, `observacoes` | `case_summary`, `notes` | Tirar linhas com senha. |
| `valor_causa`, datas de RPV e pagamento, `valor_beneficio_concedido` | exigem a seção `finance` | Sem ela, viram pendência. |

## Andamento, prazo, tarefa e documento

- **Andamento (`proceeding`):**
  - `descricao` → `description`. Sem descrição, usar "status anterior → status novo".
  - `data_andamento` → `event_date`. Sem data, usar a data de criação.
  - `tipo_andamento` → `type` (tabela fixa).
  - `visivel_para` → `visibility`.
  - Sem data e sem descrição: pendência.
- **Prazo (`deadline`):**
  - `tipo_prazo` → `deadline_type_id` (catálogo).
  - `data_vencimento` → `due_date`, obrigatório.
  - `status`, `prioridade`, horários de início e fim → campos correspondentes. Horário sem par vai para a descrição.
  - `local_endereco` → `location`; `perito_juiz_nome` → `expert_name`.
  - Prazo sem processo não entra: o AdvOS exige processo.
- **Tarefa (`task`):**
  - `titulo`, `descricao`, `status`, `prioridade`, `data_vencimento`.
  - Responsável obrigatório (membro).
  - Tarefa de robô: seguir a decisão do escritório.
- **Documento (`client_document`):**
  - Envio verificado por SHA-256 (`imports_upload_create` → PUT → `imports_upload_complete`).
  - Registro com `file_name`, `document_type` (semente) e `notes` com o rótulo original do Dash.
  - Liga ao processo quando o documento tem `processo_id` do mesmo cliente.

## Tabelas fixas (sem decisão)

| Campo | Dash → AdvOS |
|---|---|
| Status do cliente | `contrato_assinado`→`contract_signed` · `aguardando_assinatura`→`awaiting_signature` · `ativo`→`active` · `cancelado`→`cancelled` · `lead`→`lead` · `negociacao`/`em_negociacao`→`negotiation` · `finalizado`/`concluido`→`completed` · `arquivado`→`archived` · `retrabalho`→`rework` |
| Estado civil | solteiro(a)→`single` · casado(a)→`married` · divorciado(a)/separado(a)→`divorced` · viúvo(a)→`widowed` · união estável→`common_law` |
| Canal (cliente) | anúncio Facebook/Instagram→`facebook_ad` · anúncio Google→`google_ad` · indicação→`referral` · site→`website` · WhatsApp→`whatsapp` · telefone/ligação→`phone` · presencial→`in_person` · outro→`other` |
| Canal (contrato) | `organic`, `anuncio_facebook`, `anuncio_instagram`, `anuncio_google`, `indicacao`, `outros`. Fora disso: `outros`, com o canal original na nota. |
| Relação com o processo anterior | `primeiro_processo`→`first_process` · `recurso`→`appeal` · `nova_tentativa`→`new_attempt` · `mudanca_estrategia`→`strategy_change` · `administrativo_concluido`→`administrative_completed` · outro→`other` |
| Tipo de andamento | `peticao`→`petition` · `despacho`→`order` · `recurso`→`appeal` · `mudanca_status`/`edicao_processo`→`status_change` · `upload_documento`→`document_upload` · `edicao_cliente`→`client_edit` · `entrada_sistema`→`system_entry` · `importacao_inicial`→`initial_import` · `movimentacao_automatica`→`automatic_movement` · `outros`→`other` |
| Visibilidade do andamento | todos→`all` · jurídico→`legal` · administrativo→`administrative` · financeiro→`financial` |
| Status do prazo | `pendente`→`pending` · `cumprido`→`fulfilled` · `vencido`→`overdue` · `cliente_ausente`/`cliente_nao_compareceu`→`client_absent` · `remarcado`→`rescheduled` · `cancelado`→`cancelled` · `documento_anexado`→`document_attached` |
| Prioridade | baixa→`low` · média→`medium` · alta→`high` · urgente→`urgent` |
| Status da tarefa | `aberta`/`pendente`→`open` · `em_andamento`→`in_progress` · `aguardando`→`waiting_on_third_party` · `concluida`→`completed` · `cancelada`→`cancelled` |
| Tipo de documento | `identity`, `medical_report`, `proof_of_address`, `court_document`, `contract`, `letter`, `power_of_attorney`, `other`: ver a semente |

## Catálogos do escritório (etapas, tipos de serviço, condições, tipos de prazo)

Cada escritório tem os seus no Dash (bootstrap: `StatusProcessual`, `TipoServicoJuridico`, `Condicao`, `TipoPrazo`).
Há dois caminhos. A escolha é da responsável e é feita no piloto.

- **A. Levar o catálogo do escritório para o AdvOS.** O MCP de importação cria catálogos:
  - `case_status`: nome e fase `administrative`, `judicial` ou `sales`; aceita `next_status_name`;
  - `legal_service_type`: nome;
  - `medical_condition`: nome;
  - `deadline_type`: nome e `slug`.

  Mantém o vocabulário do escritório e dispensa decisão. Serve para uma organização nova. **A validar no piloto:** se a
  organização nova já vem com catálogo padrão, e como o AdvOS trata nome repetido.
- **B. Casar com o catálogo que o AdvOS já tem.**
  - Nome idêntico casa sozinho.
  - O resto vai para decisão, com o contexto da fase: etapa administrativa só casa com etapa administrativa.
  - Sem correspondente, o processo entra na etapa padrão da organização e o nome original vai na nota.

  Foi o caminho usado em setembro, porque a organização já tinha catálogo em uso.

## Contratos e financeiro (se o escritório decidir levar)

- **Contrato (`crm/deal`):**
  - cliente obrigatório;
  - vendedor = membro. Vendedor inativo sai, e o contrato entra sem ele;
  - `value_cents` em centavos;
  - `status`: `active`, `completed` ou `cancelled`;
  - data de assinatura;
  - canal pela tabela fixa;
  - ID do anúncio vai para a nota.

  Contrato importado não dispara automação de vendas.
- **Financeiro:**
  - exige a seção `finance`;
  - cada parcela do Dash vira uma receita com `installment_total` 1;
  - responsável que não é membro vai para quem a responsável indicar, com o nome do Dash na nota;
  - receita recebida sem data fica de fora até a data ser preenchida **no Dash**;
  - conferir as somas por tipo, ao centavo, no Dash e no AdvOS.
- **Receita que não é do escritório** (ex.: venda de outro negócio registrada no mesmo Dash) não entra.
