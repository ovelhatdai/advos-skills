---
name: advos-operacao
description: Investigar, configurar e testar o AdvOS com computer use, conferindo organização, canais, agentes, conversas e entregas reais. Use quando o usuário pedir ajuda operacional ou diagnóstico no AdvOS.
---

# AdvOS: operação e diagnóstico

Versão: 0.1.3 (2026-09-23). Esta skill é um roteiro de investigação, não uma descrição garantida da versão atual do produto. Confira a interface e as permissões reais a cada uso.

## Comece pelo pedido

1. Identifique a organização ativa, a conta autenticada, o ambiente, o canal ou conversa e o resultado esperado. Não misture dados ou autorizações de escritórios diferentes.
2. Se o pedido for só análise, faça leitura. Se for execução, limite as alterações ao objetivo autorizado e confirme o estado salvo após cada mudança.
3. Prefira o navegador interno do chat com **computer use** para operar a interface, quando disponível. Observe a tela antes de clicar. Use conectores ou APIs oficiais se estiverem disponíveis e autenticados. Não altere a página por scripts ocultos no DOM.
4. Comece pelas telas navegáveis do próprio AdvOS. Nomes, rotas e recursos podem mudar.

## Mapa de um atendimento WhatsApp

Siga a mensagem de ponta a ponta: anúncio ou contato → número WhatsApp → canal → caixa de entrada → agente configurado → conversa → envio e recibo → eventual encaminhamento humano. Verifique cada elo; um painel verde em uma etapa não comprova as outras.

| Etapa | O que verificar |
| --- | --- |
| Canal | Número completo, organização, provedor, estado e caixa principal. |
| Caixa | Canal vinculado, agente padrão e acesso da equipe. |
| Agente | Ativação, instruções salvas, escopo das regras e pausa quando um humano assume. |
| Conversa | Cronologia, última entrada, anexos, última resposta, notas e motivo do encaminhamento. |
| Entrega | Registro de saída, status do provedor e confirmação no número de teste. |
| Encaminhamento | Dados reunidos, concordância do contato, responsável, fila e aceite efetivo. |

Um contador de campanha, um aviso de “salvo”, HTTP 200 ou um identificador de mensagem não prova que a pessoa recebeu a resposta. Informe qual camada foi comprovada.

## Configurar um agente de atendimento

- Use conversas autorizadas como referência de linguagem, sem copiar dados pessoais nem práticas inadequadas.
- Faça perguntas curtas e sequenciais; aproveite o que a pessoa já informou. Peça documentos pertinentes ao caso, explique a finalidade e confirme apenas o recebimento. Não declare que analisou ou validou um documento sem verificação real.
- Registre no prompt o ponto exato de passagem para uma pessoa da equipe. Quem prepara, revisa, gera e fecha contrato depende da operação do escritório; obtenha essa definição antes de configurar o fluxo.
- Trate um checklist fixo como registro de evidências. Ele não prova que todos os dados e documentos específicos daquele benefício estão completos, nem que houve concordância para o repasse ou contrato fechado.
- Nunca prometa resultado jurídico, prazo, valor ou concessão sem base verificada. Não solicite senhas, códigos de verificação ou credenciais por conversa.
- Se a organização quiser que o agente use um nome humano, respeite a apresentação escolhida, mas responda com transparência se o contato perguntar se fala com uma automação.
- Releia o prompt salvo e teste com conversa controlada. Um prompt correto não altera sozinho os filtros, checklists ou regras fixas do sistema.

## Depurar quando não responde

1. Confirme o número e a organização da mensagem recebida.
2. Compare o horário e o tipo da última entrada com a última resposta. Distinga texto, imagem, áudio e documento.
3. Confira se a conversa foi assumida por humano, se o agente está habilitado e se o canal está ligado à caixa correta.
4. Se aparecer um encaminhamento com gatilho “Palavra-chave”, leia o **motivo** antes de concluir que o cliente pediu uma pessoa. Um limite diário de IA pode gerar um encaminhamento técnico com esse rótulo em versões anteriores. Confira o limite atual e, se a interface mostrar, o uso antes de devolver a conversa ao agente. Preserve encaminhamentos de segurança ou pedidos humanos reais para análise da equipe.
5. Num bloqueio de segurança, confira a regra acionada e o texto retido apenas na área privada autorizada. Uma abertura comum como “Ótimo” pode ser um falso positivo de uma expressão regular ampla. Se confirmar, corrija a regra específica com teste de regressão e mantenha as demais proteções; não publique o texto do cliente nem devolva automaticamente o caso à IA antes da correção estar implantada.
6. Use o diagnóstico que o AdvOS expuser para correlacionar entrada, tratamento de mídia, disparo do agente, tentativa de envio e recibo. Anote apenas IDs técnicos necessários, sem conteúdo sensível.
7. Reproduza em contato de teste autorizado. Não use uma conversa real de cliente como experimento descartável.
8. Relate fato observado, causa comprovada ou hipótese em campos separados. Se uma hipótese não foi verificada, deixe-a como pendência.

## Acompanhamento e retorno ao agente

- Confira o alcance de cada opção antes de ligá-la. Um controle da organização pode afetar todos os canais. O mesmo agente também pode ser padrão em mais de uma caixa ou número: nesse caso, um controle apenas por agente alcança todos os vínculos. Localize a opção do canal específico antes de ativar o acompanhamento e, após salvar, recarregue a página para confirmar que o canal desejado ficou ligado e os demais mantiveram o estado anterior.
- Confira a janela de horário, o tempo mínimo sem resposta, as regras de opt-out e os encaminhamentos humanos antes de esperar um disparo. Um switch salvo demonstra configuração; a prova do acompanhamento exige mensagem elegível enviada e entregue pelo número correto.
- Uma conversa devolvida ao agente pode voltar a exibir “IA ativa”, mas isso não envia automaticamente uma nova resposta. Para comprovar o atendimento, observe uma nova entrada, a resposta e a entrega no número de teste.
- Uma primeira resposta entregue demonstra somente o início da conversa. Verifique em turnos separados a coleta de dados e documentos, a concordância para repasse e o recebimento efetivo pelo responsável.
- Fora da janela de atendimento do WhatsApp, o acompanhamento pode depender de modelo de mensagem aprovado e consentimento. Não prometa envio enquanto esses requisitos não forem verificados.

## Acesso e privacidade

- Uma falha de login em CLI ou API não prova ausência de permissão na conta. Confira a sessão e o papel exibidos na interface antes de pedir novos acessos.
- Pedidos de permissão devem informar recurso, papel, finalidade e duração. Não amplie acesso de outros membros sem necessidade e autorização.
- Nunca ponha token, cookie, senha, chave, CPF, dados médicos ou conteúdo de clientes em issues, prints públicos, logs compartilhados ou nesta skill.
- Verifique que a organização e os números do mentorado são os próprios antes de salvar uma configuração.

## Atualizar esta skill

Ao descobrir um comportamento novo ou corrigir uma instrução: reproduza, anote o contexto e a data, separe regra geral de particularidade de uma organização, edite a fonte versionada, revise dados sensíveis, valide o YAML e a instalação, atualize `CHANGELOG.md` e publique uma nova versão. Não trate conversas ou saídas de diagnóstico como aprendizado automático. Uma descoberta em outra tarefa pode ser incorporada aqui mediante edição explícita.
