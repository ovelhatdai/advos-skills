# Sua migração do AdvogandoDash para o AdvOS

**Em uma frase:** o Claude Code, no seu computador, lê os dados do seu escritório no Dash e grava no AdvOS em lotes,
com a sua aprovação a cada passo. Você não exporta planilha e não cadastra nada de novo.

## O que você já pode preparar agora

1. **Dash:** confirme que você entra com o perfil de **administradora do escritório**.
2. **AdvOS:**
   - confirme que você é a dona da organização do seu escritório;
   - cadastre a equipe **com o mesmo e-mail que cada pessoa usa no Dash**. É por esse e-mail que cada processo, prazo e
     tarefa chega ao responsável certo.
3. **Computador:** tenha um computador com o Claude Code e o Google Chrome instalados. Por enquanto, de preferência um
   Mac: o kit só foi testado nele.
4. **Decisões:** responda às perguntas da seção "Decisões do escritório".
5. **Arrumação no Dash** do que for fácil. Cada item abaixo, se ficar, vira pendência:
   - clientes sem CPF ou com CPF errado. Sem CPF válido, o cliente não entra no AdvOS;
   - clientes cadastrados duas vezes, com o mesmo CPF;
   - prazos ou documentos ligados ao processo de outro cliente;
   - documentos que são link do Google Drive, e não arquivo.

## Como vai ser, depois que a equipe Advogando liberar o seu escritório

| Etapa | O que acontece | O que você faz |
|---|---|---|
| 1. Conexão | O Claude abre o login do Dash no navegador. A credencial do AdvOS chega da equipe Advogando por canal privado. | Faz o login. Nunca envia senha a ninguém. |
| 2. Inventário | O Claude mostra os números do escritório, sem nomes. | Confirma o que migra. |
| 3. Mapeamento | O Claude monta a tabela de tipos (ex.: "COMP" = comprovante de protocolo). | Aprova a tabela. |
| 4. Piloto | Entram 3 clientes. | Abre os 3 no AdvOS e confere. |
| 5. Carga | O resto entra em lotes. | Aprova cada lote. |
| 6. Relatório | O que entrou, o que ficou pendente e por quê. | Distribui as pendências à equipe. |
| 7. Virada | Na data combinada, a equipe passa a trabalhar no AdvOS. | Avisa a equipe. |

**Sem o seu "ok", nada é gravado no AdvOS.**

## Cuidados

- A pasta de trabalho fica no seu computador, **fora** do Google Drive, do iCloud, do OneDrive e do Dropbox, porque tem
  dados de clientes.
- Não cole senha, token ou código no chat.
- Continue usando o Dash normalmente até a data da virada. Não apague nada no Dash durante a migração.
- O AdvOS não "atualiza" o que já foi migrado. O que mudar no Dash depois do corte vai para uma lista, para acertar à mão
  ou no delta final.

## Decisões do escritório (responder antes do piloto)

1. **O que migra?** Todos os clientes, só os ativos, ou a partir de uma data?
2. **Processo judicial ainda sem número CNJ.** O AdvOS não aceita processo judicial sem CNJ. Duas opções:
   - (a) separar para conferir depois. É o padrão;
   - (b) entrar como administrativo, com uma nota dizendo que é judicial.
3. **Financeiro:** contratos, honorários e receitas vão junto?
4. **Senhas escritas nas observações** (ex.: senha do INSS). O padrão é não levar a senha e anotar a pendência, para
   cadastrar no campo seguro do AdvOS.
5. **Documento que não baixa** (link do Drive, formato desconhecido): você aceita que fique na lista para buscar o
   original?
6. **Pessoa do Dash que não está no AdvOS:** vai ser cadastrada antes, ou os registros dela entram sem responsável?
7. **Tarefas automáticas criadas por robô no Dash.** Ficam de fora as concluídas. Quem recebe as abertas?
8. **Data da virada:** qual dia a equipe passa a trabalhar só no AdvOS?
