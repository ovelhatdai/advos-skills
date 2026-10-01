# Armadilhas da migração AdvogandoDash → AdvOS

Cada item já custou um erro numa migração real, em setembro de 2026. Formato: o que aparece → o que é → o que fazer.

## Leitura do Dash (MCP do Dash)

1. **`SNAPSHOT_PREPARING` repetido.** O MCP monta poucos pacotes por escritório de cada vez (hoje, até 3). Pedido a mais
   espera na fila.
   - Repetir a cada 3 segundos, com prazo por cliente (sugestão: 15 minutos).
   - Não aumentar o paralelismo: mais frentes só aumentam a espera.
2. **`CLIENT_BUDGET_EXCEEDED`.** É o prazo do próprio kit, não erro do servidor. Deixar o cliente para uma repassada no
   fim do lote.
3. **`SOURCE_DIVERGED`.**
   - Na primeira vez, o cliente mudou no Dash depois do corte. Fazer corte novo (2 minutos atrás) com chave nova.
   - **Se repetir com corte novo, não é mudança.** Há documento, prazo, tarefa ou contrato ligado a um processo de outro
     cliente, ou a um processo apagado. Repetir não resolve. A equipe do escritório corrige o vínculo no Dash, e o prazo
     pode estar no processo errado. Depois, baixar só esse cliente.
   - No MCP atualizado, esse caso tem erro próprio: `SOURCE_RELATIONSHIP_CONFLICT`, com a entidade em
     `details.entity`.
4. **Documento em quarentena** (`fileQuarantine`: `FILE_UNAVAILABLE` ou `LINK_ONLY`). O MCP não conseguiu o arquivo:
   - link de Google Drive privado pede login;
   - link público devolve a **página** do visualizador, não o arquivo;
   - o armazenamento respondeu erro.

   O documento vira a pendência "buscar o original e anexar". Nunca imprimir a página do Drive como se fosse o documento.
   O vídeo de confirmação vem só como link (`LINK_ONLY`), de propósito.
5. **`CONTRACT_MISMATCH`.** O pacote traz um campo que o contrato do MCP não conhece, **mesmo vazio**. Parar e chamar a
   equipe Advogando: a correção é no MCP.
6. **Lista de clientes com repetição.**
   - `listar_clientes` e `listar_processos` repetem alguns registros e pulam outros: ordenam por um campo que não existe.
   - Use `migration_source_list_clients`, que traz todos os ids do escritório com as datas.
   - Sem ela, monte a lista pela união com `listar_contratos`, que pagina certo, e confira o total contra o Dash.
7. **Data do Dash.** O `created_date` vem em UTC, sem fuso. Converter para o horário de São Paulo antes de comparar dias.
8. **Token do Dash expira.** O kit renova sozinho, com trava de arquivo. Dois processos renovando ao mesmo tempo derrubam
   um ao outro.
9. **Pacote de outro cliente.** O kit confere `sourceClientId` e o id do `Cliente` dentro do pacote. Se não baterem,
   descartar e registrar.
10. **Leitura lenta** (`BASE44_TIMEOUT`, `BASE44_UNAVAILABLE`). A base do Dash é comum a todos os escritórios. Esperar e
    repetir com intervalo crescente. Se passar de uma hora, pausar o lote.

## Gravação no AdvOS (MCP de importação)

1. **A importação só cria.** `BUSINESS_KEY_CONFLICT` quer dizer "já existe": CPF no cliente, CNJ no processo, processo +
   instância no financeiro.
   - **Nunca tirar o campo para forçar a gravação.** Isso criaria uma duplicata.
   - Registrar a pendência "já existe, conferir".
2. **Prévia não grava.** Só `imports_confirm` grava. Prévia esquecida expira; cancelar com `imports_cancel`.
3. **`REQUEST_KEY_CONFLICT`.** A chave de envio já foi usada, inclusive por uma prévia cancelada. Usar onda e chave novas.
4. **Prefixo repetido entre lotes.** O AdvOS devolve o job antigo ("replay") e não importa ninguém.
5. **Limites da organização:**
   - 1 job rodando por vez;
   - 300 pedidos por minuto;
   - até 1.000 registros por envio;
   - documento de até 25 MB.

   Conferir os limites atuais em `imports_capabilities`.
6. **`REFERENCE_NOT_FOUND` sem campo.** Quase sempre é um responsável que não é mais membro ativo. O registro entra sem o
   responsável e fica uma pendência. Tarefa exige responsável e não entra.
7. **Processo judicial sem CNJ válido** (20 dígitos). O AdvOS recusa. Seguir a decisão do escritório e nunca inventar
   número.
8. **O mesmo CNJ duas vezes no mesmo cliente.** O AdvOS aceita um processo por CNJ, e a prévia não pega a repetição
   dentro do lote: a gravação falha com `INFRASTRUCTURE_FAILURE`. O kit une os dois no mais antigo, com andamentos,
   prazos, tarefas e documentos, e registra a pendência.
9. **Várias tentativas sobre o mesmo processo de origem** (ex.: dois recursos). O AdvOS aceita um derivado de cada tipo
   por processo de origem. O kit encadeia as tentativas, cada uma apontando para a anterior, e anota a origem real.
10. **Formato do documento.**
    - `application/octet-stream` e HTML são recusados (`UPLOAD_INVALID`). O kit descobre o formato pelos bytes.
    - Documento gerado em HTML no Dash vira PDF pelo Chrome local.
    - Página do Google Drive nunca vira PDF.
11. **Nome de arquivo ou chave de envio com mais de 200 caracteres** são recusados. O kit encurta e mantém a extensão.
12. **Documentos que o validador recusa:** assinatura `.p7s` e PDF com bytes antes de `%PDF`. Ficam como pendência, com o
    original preservado no Dash.
13. **Parcelas.** Nunca enviar o total de parcelas: o AdvOS criaria o grupo inteiro. Cada parcela do Dash vira uma receita
    com `installment_total` 1.
14. **Pessoas.** O AdvOS liga pessoa pelo `userId` do membro, não pelo id do Dash nem pelo nome. Mapear por e-mail. Ids
    criados no mesmo lote compartilham o começo: nunca comparar id por prefixo.
15. **Job parado em `validating`.** Já aconteceu por cerca de 2 horas, sem erro. Esperar e avisar a equipe. **Não reenviar
    com outra chave**: quando o primeiro destravar, os dois gravariam.
16. **Cadastro que o AdvOS recusa.**
    - Pessoa física precisa de CPF válido. Sem ele, o cliente não entra, e os processos e documentos dele também não.
    - Telefone inválido e data de nascimento no futuro são recusados.

    Corrigir no Dash e baixar o cliente de novo.
17. **Lista de clientes do AdvOS pela API de leitura.** A primeira página vem em ordem decrescente de id e as seguintes
    crescem a partir do menor id dela: registros ficam de fora. Começar o cursor em
    `00000000-0000-0000-0000-000000000000`.

## Rótulos e decisões

1. **Rótulo livre pode ter nome de pessoa** ("PROCESSO FULANO", "TESTEMUNHA 2 MARIA").
   - O kit troca o nome do cliente por `[nome]` antes de decidir.
   - Rótulo que começa com "testemunha", "vídeo testemunha" ou "extrato de informações do benefício" herda a decisão da
     família, **só se todas** as decisões da família concordarem.
   - Nome de pessoa nunca vai para a semente nem para relatório compartilhado.
2. **Rótulo genérico** ("COMP", "DOC", "registro", "relatório") muda de sentido entre escritórios. Abrir um documento e
   contar palavras-chave por tipo, **sem imprimir o texto**, que pode ter CPF e dado de saúde. PDF escaneado sem texto
   passa por OCR local. Depois, apagar a cópia.
3. **Uma decisão vale para todos os documentos com o mesmo rótulo.** Errar custa em lote. E o que já foi gravado com o
   tipo errado não se corrige pela importação: vira pendência de acerto manual.
4. **Foto da casa não é comprovante de residência.** Uma sugestão automática errou isso duas vezes.
5. **Sugestão automática também erra.** Revisar as de confiança baixa e as que contradizem um precedente. Exemplo: um
   modelo sugeriu "identidade" para "cadastro único" digitado errado.

## Operação

1. **A rede caiu:** o kit retoma de onde parou. Não recomeçar do zero.
2. **Script rodando não se edita.**
3. **Uma pasta por lote**, com `pacotes/`, `estado.json` (fase de cada cliente) e `pendencias.jsonl`.
4. **"senha" nas observações:** tirar as linhas com senha, levar o resto e registrar uma pendência. O Dash guarda senha em
   texto aberto.
5. **Cadastro duplicado no Dash** (o mesmo CPF em dois cadastros). O AdvOS aceita um cliente por CPF, e esse cliente
   recebe os processos e contratos dos dois. Não é duplicata, mas conferir com a responsável.
6. **Cliente com processos que alternam administrativo e judicial.** Levar a cadeia: processo de origem, relação com o
   anterior e ordem cronológica.
7. **Horário em relatório vem do relógio.** Em sessão longa, a estimativa adiantou mais de uma hora, várias vezes.
