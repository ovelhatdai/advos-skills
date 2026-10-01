# Kit de scripts — AdvogandoDash → AdvOS

Versão 0.1.0 (pré-lançamento), de 01/10/2026. É o kit que a `SKILL.md` descreve, generalizado a partir dos
scripts da migração real de um escritório previdenciário (setembro de 2026).

**Estado:** testado só offline (regressão com pacotes daquela migração, teste do decisor e testes com Dash, AdvOS e OAuth
falsos). **Ainda não rodou contra o Dash nem o AdvOS de outro escritório.** Depende de a equipe
Advogando liberar o escritório no MCP do Dash e emitir a credencial de importação da organização.

## Antes de tudo

- Python 3.11 ou mais novo, só biblioteca padrão (nada de `pip`). No Mac, se o `python3` travar pedindo a licença do
  Xcode, use `DEVELOPER_DIR=/Library/Developer/CommandLineTools python3`.
- Google Chrome (documento que o Dash gerou em HTML vira PDF pelo Chrome local).
- Rodar os comandos de dentro desta pasta `ferramentas/`. O kit só grava na pasta de trabalho.
- **Pasta de trabalho:** `~/migracao-advos` (ou a variável `MIGRACAO_ADVOS_HOME`). Ela guarda dado de cliente: o kit se
  recusa a rodar se ela estiver no Google Drive, iCloud (inclusive Mesa e Documentos), OneDrive ou Dropbox.
- Só macOS: a trava de arquivo usa `fcntl` e o OCR usa o Vision do macOS. O caminho comum do Chrome no Windows é
  reconhecido, mas o kit não foi testado no Windows.

```
~/migracao-advos/
  config.json            escritório, namespace, ids do Dash e do AdvOS, decisões do escritório
  segredos/  (700)       dash.json, advos-import.txt, advos-leitura.txt (600; nunca aparecem na tela)
  referencia/            identidade.json, clientes.json, bootstrap.json, advos-catalogos.json,
                         advos-membros.json, membros.json, membros-sem-par.json
  decisoes/              decisoes.json, fila.json, tabela.csv (rótulos podem ter nome de pessoa: ficam aqui)
  lotes/prefixos.json    registro dos prefixos já usados (trava de prefixo repetido)
  lotes/<lote>/          lote.json, alvos.json, pacotes/, estado.json, pendencias.jsonl,
                         conferencia.json, conferencia-visual.csv, relatorio.html, pendencias.csv, resumo.html
```

## Fases (as mesmas da SKILL.md)

Cada fase termina num portão: mostrar a prova à responsável e seguir só com o "ok" dela.

### Fase 0 — Preparar a máquina

| Comando | O que faz | Grava |
|---|---|---|
| `python3 config.py iniciar <escritorio>` | cria a pasta; confere nuvem, Python e Chrome. `<escritorio>` é um apelido curto (ex.: `silva-adv`) | `config.json`, subpastas; namespace `advogandodash-<escritorio>` |

### Fase 1 — Conectar e provar a identidade (só leitura)

| Comando | O que faz | Grava |
|---|---|---|
| `python3 conectar_dash.py` | abre o login do Dash no navegador (OAuth com PKCE e registro dinâmico). Entrar com o **administrador do escritório**. Recusa perfil que não é `admin_escritorio`/`admin` e qualquer escopo além dos 4 de leitura | `segredos/dash.json`; escritório no `config.json` |
| `python3 config.py guardar advos-import` | **no Terminal, fora do chat**: cola a credencial de importação que a equipe Advogando mandou por canal privado (não aparece na tela) | `segredos/advos-import.txt` |
| `python3 identidade.py` | `migration_source_whoami` + `imports_capabilities`; recusa se o escritório ou a organização mudarem | ids no `config.json`; `referencia/identidade.json` |

### Fase 2 — Inventário (só leitura)

| Comando | O que faz | Grava |
|---|---|---|
| `python3 inventario.py` | ids pela união de `listar_contratos`, `listar_clientes` e `listar_processos`, sem repetir; status de quem só aparece por contrato/processo vem da ficha. Mostra contagens por fonte, status e ano: **conferir o total com a tela do Dash** | `referencia/clientes.json` |
| `python3 inventario.py alvos piloto --ids id1,id2,id3` | cria o lote do piloto (3 clientes escolhidos com a responsável) | `lotes/piloto/` |
| `python3 inventario.py alvos lote-01 [--status ativo,...] [--desde AAAA-MM-DD] [--ate ...] [--max N]` | cria um lote pelo recorte que a responsável aprovou | `lotes/lote-01/` |

O nome do lote vira o prefixo das chaves de envio (nome + id próprio). Lote apagado não pode ser recriado com o mesmo
nome. O primeiro pacote baixado guarda o bootstrap do escritório (etapas, tipos, condições, tipos de prazo, usuários)
em `referencia/bootstrap.json`.

### Fase 3 — Mapeamento e decisões

1. **Decisões do escritório** (`python3 config.py definir <opção> '<json>'`):

   | Opção | Padrão | Outras |
   |---|---|---|
   | `judicial_sem_cnj` | `"separar"` (fica para conferência manual) | `"administrativo"` (entra como administrativo, com o status judicial e o número informado na nota) |
   | `tirar_senha_das_observacoes` | `true` (linha com "senha" não vai; vira pendência para o campo seguro) | `false` |
   | `tarefas_automaticas` | `[]` | `[{"prefixos": ["AVISO AUTOMÁTICO"], "abertas_para": "e-mail do membro ou userId"}]`: tarefa de robô concluída não migra; aberta vai para quem a regra indica |
   | `catalogos` | `"casar"` (com o catálogo do AdvOS) | `"importar"` (leva o catálogo do escritório; a validar no piloto) |

2. **Equipe:** obter `referencia/advos-membros.json` (ver "Membros e catálogos do AdvOS") e rodar `python3 membros.py`.
   Liga por e-mail. Quem ficar sem par vai para `referencia/membros-sem-par.json`; a responsável escolhe entre cadastrar
   a pessoa no AdvOS (e rodar de novo) ou deixar os registros entrarem sem responsável. Se a lista do AdvOS veio sem
   e-mail, o script sugere pelo nome; depois de a responsável conferir: `python3 membros.py --aceitar-nomes`.
3. **Catálogos:** no modo `casar`, `python3 catalogos_advos.py` (com a chave de leitura) grava
   `referencia/advos-catalogos.json`. No modo `importar`, não precisa ler nada do AdvOS.
4. **Rótulos (tipo de documento, andamento, etapa, serviço, condição, tipo de prazo):**
   - `python3 baixar_pacotes.py piloto` e `python3 carga.py piloto` (simulação: converte, não envia nada e põe na fila
     os rótulos que nenhuma regra resolveu);
   - `python3 decisor.py fila` → o Claude decide. Item com `"semente": {"confianca": "abrir o documento"}`: abrir um
     documento antes com `python3 espiar_documento.py piloto "<rótulo exato>"` (conta palavras-chave por tipo, não
     imprime o texto, apaga a cópia);
   - `python3 decisor.py responder <chave> <valor>`;
   - `python3 decisor.py tabela` → `decisoes/tabela.csv` para a responsável aprovar (**portão 3**).

   Cascata do decisor, sem modelo externo: decisão já tomada → nome idêntico → semente
   (`../referencias/semente-tipos-documento.json`, só "alta") → mesmo rótulo com outra grafia, mesmas palavras ou mesma
   família, a partir das decisões deste escritório → fila do Claude.

### Fase 4 — Piloto (primeira gravação)

1. OK da responsável para os 3 clientes do piloto.
2. `python3 carga.py piloto` (simulação) → mostrar os números → `python3 carga.py piloto --gravar`.
3. `python3 conferir.py piloto` (prova pela chave de origem) + conferência visual da responsável no AdvOS, com
   `lotes/piloto/conferencia-visual.csv` (nome, links do Dash e do AdvOS, contagens). **Portão 4.**

### Fase 5 — Carga em ondas

1. OK da responsável para o lote: quantidade, período e prefixo (aparece no `inventario.py alvos`).
2. `python3 baixar_pacotes.py lote-01` em segundo plano. Até 3 pacotes ao mesmo tempo (padrão); `BUDGET=900`
   segundos por cliente. Retoma de onde parou; quem estourou o prazo vai numa repassada (rodar de novo).
3. `python3 carga.py lote-01 --gravar` quantas vezes for preciso: cada execução grava **uma onda de até 20 clientes**
   (`--max` muda), na ordem cadastro → jurídico → documentos, e para em "nada novo para importar". Antes de gravar,
   confere o escritório do token e a organização da credencial. Cliente com rótulo esperando decisão fica fora da onda.
4. `python3 conferir.py lote-01` a cada onda. **Portão 5:** tudo o que foi marcado como gravado aparece no
   `imports_lookup`.

### Fase 6 — Conferência e relatório

| Comando | Grava |
|---|---|
| `python3 conferir.py <lote>` | `conferencia.json` (só ids e números) e `conferencia-visual.csv` (com nomes) |
| `python3 relatorio.py <lote>` | `relatorio.html` e `pendencias.csv` (com nomes: só na pasta de trabalho); `resumo.html` (sem nomes: pode ser compartilhado) |

### Fase 7 — Delta final e virada

- Na véspera, `python3 inventario.py` de novo e um lote novo com quem entrou depois do corte
  (`inventario.py alvos delta-01 --desde <data do corte>`): carga normal.
- **Acréscimo em cliente já migrado** (andamento, prazo ou documento novo) **ainda não está no kit genérico** (a migração de setembro usou
  scripts próprios de delta). Até lá, levar à equipe Advogando. Registro alterado depois do corte: a importação não atualiza; vai
  para a lista de acerto na tela.
- Fechar: pedir à equipe Advogando a revogação da credencial de importação; apagar `segredos/dash.json` e
  `segredos/advos-import.txt`. Guardar a pasta de trabalho até o aceite.

## O que é só leitura e o que grava

| Script | Dash | AdvOS | Grava localmente |
|---|---|---|---|
| `config.py` | — | — | `config.json`, `segredos/` |
| `conectar_dash.py` | login OAuth | — | `segredos/dash.json` |
| `identidade.py`, `inventario.py`, `baixar_pacotes.py` | leitura | `identidade.py`: `imports_capabilities` (leitura) | referência, lotes |
| `catalogos_advos.py` | — | GET com a chave de leitura | `referencia/advos-*.json` |
| `membros.py`, `decisor.py`, `converter.py` | — | — | referência, decisões |
| `espiar_documento.py` | ticket de arquivo (leitura) | — | temporário apagado no fim |
| `carga.py` (sem `--gravar`) | — | — | só a fila de decisão |
| `carga.py --gravar` | ticket de arquivo (leitura) | **grava** (prévia → confirmação) | estado e pendências do lote |
| `conferir.py` | — | `imports_lookup` (leitura) | conferência do lote |
| `relatorio.py` | — | — | relatórios do lote |

## Membros e catálogos do AdvOS: de onde vêm

Conferido na documentação da API do AdvOS (versão de 29/09/2026) e nas permissões de cada rota.

- **Chave de leitura `advos_sk_`:** só o dono da organização cria, com `POST /api/v1/server-api-keys` (no código do
  AdvOS de 29/09 não há tela para isso: precisa da sessão do dono). Ela só lê rotas cuja guarda de permissão está entre
  as da chave (`process:read`, `client:read`, `document:read`…). Guardar com `python3 config.py guardar advos-leitura`.
- **Catálogos — a chave serve.** `GET /api/v1/case-statuses`, `/legal-service-types`, `/medical-conditions` e
  `/deadline-types` têm a guarda `process:read`. É o que o `catalogos_advos.py` lê.
- **Membros com e-mail — a chave NÃO serve.** `GET /api/v1/members` exige `member:invite` (403 com a chave). A chave lê
  `GET /api/v1/tasks/assignees` (`process:read`): todos os membros com `userId` e nome, **sem e-mail**. Por isso o
  `membros.py` sugere pelo nome e só liga depois de a responsável conferir.
- **Alternativas para ter os e-mails** (a validar no piloto): a dona, logada no AdvOS no navegador, abre
  `https://api.advos.ai/api/v1/members?limit=100` e salva a resposta como `referencia/advos-membros.json` (o
  `membros.py` aceita esse formato); ou monta a lista à mão no formato `[{"userId": "...", "email": "...", "name": "..."}]`.
- **Sem chave de leitura:** usar `catalogos: "importar"` (leva o catálogo do escritório; não precisa ler o do AdvOS) e a
  lista de membros pelo navegador.

## Testes

- `teste_decisor_trava.py`: trava e cascata do decisor. **Rodar numa cópia fora do Drive** (grava ao lado, em `dec/`).
- Regressão com pacotes reais da migração de setembro e testes com Dash, AdvOS e OAuth falsos: ficam com a equipe
  Advogando, fora deste kit (têm dado de cliente).

## Limites conhecidos

- Financeiro (contratos, honorários, receitas) não vai: vira pendência "exige credencial finance".
- Campos novos do cliente no AdvOS (mãe, pai, PIS, CTPS, benefício, número e complemento do endereço): o `Cliente` do
  Dash não tem campo correspondente nos contratos v4 a v6. Mapear quando um contrato novo trouxer.
- Modo `importar`: a validar no piloto se a organização nova já vem com catálogo padrão e como o AdvOS trata nome
  repetido. Se o AdvOS recusar um item do catálogo, os processos que dependem dele não entram (pendência) e esse item
  passa para o modo `casar`.
- Senha nas observações: sai a linha que tem a palavra "senha". Senha escrita sozinha na linha de baixo não é
  detectada (não apareceu nos pacotes da migração de setembro).
- E-mail fora do padrão do AdvOS: a prévia recusa, a carga tira o campo e registra a pendência (como na migração de setembro).
