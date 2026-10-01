---
name: advogandodash-para-advos
description: Migrar o histórico de um escritório do AdvogandoDash para o AdvOS, MCP→MCP, com portões de aprovação da responsável. Cobre conexões e identidade, inventário, mapeamento, piloto, carga em ondas, conferência pela chave de origem e virada. Use quando pedirem "migrar do Dash para o AdvOS", "levar meus clientes para o AdvOS", "importar do AdvogandoDash", "conferir a migração" ou "virada para o AdvOS".
---

# AdvogandoDash → AdvOS

Versão 0.1.0 (pré-lançamento), de 01/10/2026. O procedimento vem da migração real de um escritório previdenciário, em setembro
de 2026. **Ainda não roda em outro escritório.** Antes, a equipe Advogando precisa concluir os pré-requisitos dela
(abaixo).

## O que a skill faz e o que não faz

- Lê o Dash **só** pelo MCP do Dash (`https://mcp.advogandodash.com.br/mcp`, ferramentas `migration_source_*`), com o
  login de administradora do próprio escritório.
- Grava no AdvOS **só** pelo MCP de importação (`https://api.advos.ai/mcp/imports`). Toda gravação passa por prévia,
  confirmação e resultado.
- **Não usa** CSV, planilha, SQL, cópia manual, upload avulso, raspagem de tela nem senha de ninguém. O navegador serve só
  para os logins (OAuth).
- **Não corrige** o que já existe no AdvOS, porque a importação só cria. Registro existente com dado diferente é corrigido
  por alguém da equipe, na tela.
- **Não decide** regra do escritório. Pergunta à responsável (ver "Decisões do escritório").

## Pré-requisitos

### Da equipe Advogando (antes do primeiro uso em qualquer escritório)

1. **MCP do Dash liberado para o escritório.** Hoje ele aceita um único escritório. Para os demais, o
   `migration_source_whoami` responde `TENANT_FORBIDDEN`.
2. **Credencial de importação do AdvOS para a organização da mentorada.** Só o administrador global do AdvOS emite. As
   seções são `crm`, `legal` e `documents`; `finance` entra se o financeiro for junto. A credencial chega por canal
   privado e é revogada no fim.
3. **Varredura dos campos do escritório no Dash.** Se o escritório tiver um campo antigo que o contrato do MCP não
   conhece, o pacote falha com `CONTRACT_MISMATCH` até o contrato ser atualizado.
4. **Data agendada.** O Dash de todos os escritórios usa a mesma base (Base44). Duas migrações grandes ao mesmo tempo
   deixam as duas lentas ou derrubam as duas (`BASE44_UNAVAILABLE`).

### Da mentorada

- Login de **administradora do escritório** (`admin_escritorio`) no AdvogandoDash.
- Organização no AdvOS em que ela é a dona. A equipe precisa estar cadastrada lá **com o mesmo e-mail do Dash**: é pelo
  e-mail que o responsável de cada processo, prazo e tarefa é ligado.
- Claude Code, Python 3.11 ou mais novo e Google Chrome. O kit só foi testado no macOS.
- Uma pasta de trabalho **fora** de qualquer pasta sincronizada (Google Drive, iCloud, OneDrive ou Dropbox), porque ela
  guarda dado de cliente. O padrão é `~/migracao-advos/`.
- **Lista dos membros do AdvOS com e-mail.** A dona entra no AdvOS no navegador, abre
  `https://api.advos.ai/api/v1/members?limit=100` e salva a resposta em `referencia/advos-membros.json`. Também dá para
  montar a lista à mão. A chave de leitura não serve para isso: essa rota responde 403 a ela.
- **Opcional: chave de leitura do AdvOS (`advos_sk_`)**, para casar com os catálogos que a organização já tem. Só a dona
  cria, pela API e logada; o AdvOS ainda não tem tela para isso. Sem a chave, os catálogos vão no modo `importar`.
- Respostas para as "Decisões do escritório".

O kit de scripts fica em `ferramentas/`. Os comandos de cada fase estão em `ferramentas/LEIA-ME.md`. Ele roda no macOS.
**Ainda não leva contratos nem financeiro:** esses registros viram pendência, e entram numa versão seguinte.

## Regras (valem em toda a execução)

1. Só MCP→MCP.
2. Nunca imprimir, colar no chat ou gravar em log token, senha ou código. Credenciais ficam em
   `~/migracao-advos/segredos/`, com permissão 600.
3. Dado de cliente só na pasta de trabalho. Relatório para compartilhar tem só contagens.
4. **Toda gravação no AdvOS exige OK explícito da responsável para aquele lote**, sempre com piloto antes. O OK de um lote
   não vale para o próximo.
5. Um escritório e uma organização por vez. Antes de cada lote, conferir:
   - o escritório do token do Dash é o combinado;
   - a organização da credencial do AdvOS é a combinada.
6. Prefixo de envio único por lote. Se um prefixo se repetir, o AdvOS devolve o trabalho antigo ("replay") e não importa
   nada.
7. "Feito" só com prova: releitura no AdvOS pela chave de origem (`imports_lookup`) e contagem. Prévia, job iniciado,
   aviso de "salvo" ou HTTP 200 não provam nada.
8. Horário escrito em relatório vem do relógio (`date`), nunca de estimativa.
9. Não editar script que está rodando: parar, editar e retomar. O kit retoma de onde parou.

## Fases e portões

Cada fase termina num **portão**: mostrar a prova à responsável e seguir só com o "ok" dela.

### Fase 0 — Preparar a máquina

Criar a pasta de trabalho com as subpastas `segredos/`, `referencia/` e `lotes/`, instalar o kit e conferir Python e
Chrome.

**Portão 0:** caminho da pasta confirmado fora da nuvem e kit instalado.

### Fase 1 — Conectar e provar a identidade (só leitura)

1. **Dash.** O script de login abre o navegador e a mentorada entra com o usuário administrador. O token vai direto para
   `segredos/`, sem aparecer na tela. Os escopos pedidos são só de leitura:
   `read:clientes read:processos read:prazos read:financeiro`. Token com escopo de escrita é recusado de propósito.
2. **`migration_source_whoami`.** Devolve o escritório (id e nome), o perfil e os escopos.
3. **AdvOS.** `imports_capabilities`, com a credencial de importação, devolve o `organizationId`, as seções liberadas e os
   limites.

**Portão 1:** "Dash: escritório X → AdvOS: organização Y." A responsável confirma os dois nomes.

### Fase 2 — Inventário (só leitura)

1. **Lista de clientes do escritório.**
   - Usar `migration_source_list_clients`: devolve o id e as datas de criação e de alteração de todos os clientes, sem
     nome.
   - Se o MCP ainda não tiver essa ferramenta, juntar os ids de `listar_contratos`, que pagina certo, com os de
     `listar_clientes` e `listar_processos`, sem repetir. Essas duas repetem alguns registros e pulam outros.
   - Conferir o total contra a tela do Dash.
2. **Contagens no Dash:** clientes por status e por ano de cadastro. A contagem detalhada (processos, andamentos, prazos,
   tarefas, documentos) sai dos pacotes, na fase 4.
3. **O que já existe no AdvOS.** Numa organização nova, o esperado é quase nada. Se já houver clientes (cadastro manual
   ou planilha antiga), sondar com uma prévia de `import_crm`, que não grava, e cancelar com `imports_cancel`. CPF
   repetido volta como `BUSINESS_KEY_CONFLICT`. Esse cliente não é criado de novo: vira caso de acréscimo, conferido com
   a responsável.
4. **Catálogos do escritório.** O primeiro lote de um pacote é o bootstrap do escritório: etapas (`StatusProcessual`),
   tipos de serviço, condições, tipos de prazo e usuários. Guardar em `referencia/`.

**Portão 2:** números na tela, sem nomes. A responsável confirma o escopo: todos os clientes, só os ativos ou só a partir
de uma data.

### Fase 3 — Mapeamento e decisões

1. **Equipe.** Ligar cada usuário do Dash a um membro do AdvOS pelo e-mail. O AdvOS liga a pessoa pelo `userId` do
   membro. Quem ficar sem par vai para uma lista para a responsável. Ela escolhe entre duas saídas:
   - cadastrar a pessoa no AdvOS antes da carga;
   - aceitar que os registros entrem sem responsável. Tarefa não entra sem responsável e vira pendência.
2. **Catálogos:** etapas, tipos de serviço, condições e tipos de prazo. São dois modos no `config.json`:
   - `importar`: leva o catálogo do escritório;
   - `casar`: liga ao catálogo que o AdvOS já tem, e exige a chave de leitura.

   Ver `referencias/mapeamento-dash-advos.md`.
3. **Rótulos livres (tipo de documento).**
   - Usar a semente `referencias/semente-tipos-documento.json`.
   - Rótulo marcado "abrir o documento": abrir um documento com esse rótulo, fora da nuvem. Contar palavras-chave por
     tipo, **sem imprimir o texto**. Decidir, registrar e apagar a cópia.
4. **Tipos fixos:** andamento, status do cliente, estado civil, canal, prioridade e status de prazo e de tarefa. Seguem a
   tabela do mapeamento, sem decisão.

**Portão 3:** a responsável aprova a tabela de correspondências (rótulo → tipo), com os casos ambíguos já resolvidos.

### Fase 4 — Piloto (primeira gravação)

1. Escolher 3 clientes:
   - um simples;
   - um com processo judicial;
   - um com muitos documentos.

   Pedir o OK da responsável para gravar esses 3.
2. Baixar os pacotes (um cliente por pacote), converter, fazer a prévia e confirmar.
3. Conferir de três jeitos:
   - `imports_lookup` pela chave de origem: tudo presente;
   - contagens de cada cliente iguais às do pacote;
   - **conferência visual da responsável no AdvOS**: cadastro, processos, prazos, e os documentos abrem.

**Portão 4:** a responsável aprova o piloto. Todo ajuste vira decisão registrada antes da carga.

### Fase 5 — Carga em ondas

1. **OK da responsável para o lote:** quantidade, período e prefixo.
2. **Baixar os pacotes em segundo plano.**
   - Até 3 pacotes ao mesmo tempo por escritório; mais que isso só aumenta a fila.
   - No melhor caso, 90 a 130 clientes por hora. Cai quando a base do Dash está carregada.
3. **Converter e gravar em ondas de cerca de 20 clientes,** nesta ordem:
   - cadastro (`import_crm`);
   - processos, andamentos, prazos e tarefas (`import_legal`);
   - documentos (`imports_upload_create` → envio → `imports_upload_complete` → `import_documents`).

   Uma onda por vez: o AdvOS roda um job por organização.
4. **Cliente com decisão pendente fica fora da onda.** Entraria com o valor errado. Volta na próxima onda, depois da
   decisão.
5. **Acompanhar pelo log** e relatar só contagens.

**Portão 5 (a cada lote):** tudo o que foi gravado aparece no `imports_lookup`, e as pendências estão listadas.

### Fase 6 — Conferência e relatório

1. **Por entidade:** Dash (pacotes) × gravado (lookup) × pendências. Nos documentos, o SHA-256 tem de ser igual ao do Dash.
2. **Relatório local em HTML.** A versão com nomes fica só na pasta de trabalho; a versão sem nomes pode ser compartilhada.
3. **Lista de pendências para a equipe:** o cliente, o item e o motivo. Os motivos estão em `referencias/armadilhas.md`.

**Portão 6:** a responsável recebe o relatório e a lista.

### Fase 7 — Delta final e virada

1. **Combinar a data da virada.** A partir dela, a equipe trabalha no AdvOS.
2. **Na véspera, fazer um novo inventário** e tratar cada grupo assim:
   - cliente novo desde o corte → carga normal;
   - registro novo de cliente já migrado (andamento, prazo, documento) → acréscimo;
   - registro **alterado** depois do corte → a importação não atualiza. Vai para uma lista, para acertar na tela.
3. **Fechar os acessos.**
   - Pedir à equipe Advogando a revogação da credencial de importação.
   - Apagar o token do Dash de `segredos/`.
4. **Guardar os pacotes até o aceite.** Depois, apagar a pasta de trabalho, conforme o combinado. Nunca apagar nada no
   Dash.

## Decisões do escritório (perguntar antes do piloto)

1. **Escopo:** todos os clientes ou um recorte (só os ativos, ou a partir de uma data)?
2. **Processo judicial sem número CNJ** (ainda não ajuizado). O AdvOS não aceita processo judicial sem CNJ. Nunca inventar
   número. Duas opções:
   - **(a) separar para conferência manual depois.** É o padrão;
   - **(b) entrar como administrativo,** com o status judicial numa nota.
3. **Financeiro:** contratos, honorários e receitas vão junto? O kit ainda não leva esses registros: ficam como
   pendência até a versão seguinte. Quando entrarem, vão exigir credencial com `finance` e conferência das somas ao
   centavo.
4. **Senha nas observações** (ex.: senha do INSS). O padrão é tirar as linhas com senha e deixar uma pendência, para
   cadastrar no campo seguro do AdvOS. Senha nunca vai para campo comum.
5. **Documento que não baixa:** link de Google Drive privado, página no lugar do arquivo ou formato desconhecido. Fica a
   pendência "buscar o original".
6. **Responsável que não é membro do AdvOS:** cadastrar antes ou deixar o registro entrar sem responsável?
7. **Tarefas automáticas** (avisos que um robô criou no Dash). O padrão é:
   - as concluídas não migram;
   - as abertas vão para quem a responsável indicar.
8. **Vídeo de confirmação:** vai como link, nas observações do cliente.

## Quando parar e chamar a equipe Advogando

- `TENANT_FORBIDDEN` no `whoami` ou no pacote: o escritório ainda não foi liberado no MCP.
- `CONTRACT_MISMATCH`: campo novo no Dash. O contrato do MCP precisa ser atualizado.
- `INFRASTRUCTURE_FAILURE`, ou job parado em `validating` por mais de 2 horas.
- `SOURCE_RELATIONSHIP_CONFLICT`, ou `SOURCE_DIVERGED` que se repete com corte novo. Não é mudança: há documento ou
  prazo ligado a processo de outro cliente, ou a um processo apagado. O erro novo diz a entidade (ex.:
  `PrazoProcessual`). A equipe do escritório corrige o vínculo no Dash e o cliente é baixado de novo.
- Qualquer pedido para apagar algo, no Dash ou no AdvOS.
- Pacote com dado de outro cliente. O kit confere o id e descarta, mas o caso precisa ser comunicado.

## Referências

- `GUIA-DA-MENTORADA.md`: o que a responsável faz, em linguagem simples.
- `referencias/armadilhas.md`: erros que já aconteceram e o que fazer em cada um.
- `referencias/mapeamento-dash-advos.md`: campo a campo, tabelas fixas e catálogos.
- `referencias/semente-tipos-documento.json`: 265 rótulos de documento já decididos (200 claros e 65 para abrir o
  documento).
