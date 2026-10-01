# Skills AdvOS para mentorados

Pacote genérico para usar o AdvOS no **próprio escritório**. Não inclui acesso ao AdvOS, credenciais, dados de clientes ou configuração de outra organização.

| Skill | Versão | Para quê |
| --- | --- | --- |
| `advos-operacao` | 0.1.3 — 2026-09-23 | Configurar, testar e depurar o AdvOS. |
| `advogandodash-para-advos` | 0.1.0 — 2026-10-01 (pré-lançamento) | Migrar o histórico do escritório do AdvogandoDash para o AdvOS. |

## Instalação (`advos-operacao`)

1. Baixe o ZIP da versão publicada ou clone o repositório da skill.
2. Coloque a pasta `advos-operacao` no diretório de skills aceito pelo seu assistente. No Codex, normalmente é `~/.codex/skills/advos-operacao/`; em projetos que usam `.agents/skills/`, pode ser a pasta correspondente do projeto. Consulte o manual do seu assistente se o diretório for diferente.
3. Confira se o arquivo `advos-operacao/SKILL.md` está presente, incluindo o cabeçalho YAML.
4. Abra uma tarefa nova e peça: “Use a skill advos-operacao para conferir meu canal WhatsApp no AdvOS e me dizer o que está verificado e o que falta testar.”

Para operar pela tela, use um assistente que tenha **computer use** habilitado e dê acesso ao seu navegador autenticado. A skill descreve o procedimento; instalar a pasta não concede acesso nem inicia um agente sozinho.

## Exemplos de uso (`advos-operacao`)

- “Use advos-operacao para verificar por que a conversa de teste não recebeu resposta depois de uma imagem.”
- “Use advos-operacao para configurar o agente da minha caixa WhatsApp e testar o encaminhamento ao vendedor.”
- “Use advos-operacao para revisar o atendimento de hoje. Separe recebido, respondido e entregue.”
- “Use advos-operacao para depurar o sistema. Se encontrar uma regra geral confirmada, proponha uma atualização da skill sem incluir dados de clientes.”

## Migração do AdvogandoDash para o AdvOS (`advogandodash-para-advos`)

**Pré-lançamento.** A skill e o kit de scripts estão prontos. Cada escritório só migra depois que a equipe Advogando:

- libera o escritório no MCP do AdvogandoDash;
- emite a credencial de importação da organização no AdvOS.

Antes disso, o login no Dash funciona, mas a primeira leitura responde `TENANT_FORBIDDEN`.

O que vem na pasta:

- `SKILL.md`: o procedimento em fases, com um portão de aprovação da responsável em cada uma;
- `GUIA-DA-MENTORADA.md`: o que a responsável faz e o que já pode preparar;
- `referencias/`: armadilhas, mapeamento campo a campo e a semente de tipos de documento;
- `ferramentas/`: o kit de scripts. O `LEIA-ME.md` traz os comandos de cada fase.

Requisitos:

- Mac com Claude Code, Python 3.11 ou mais novo e Google Chrome;
- login de administradora do escritório no AdvogandoDash;
- organização no AdvOS com a equipe cadastrada com o mesmo e-mail do Dash.

Instalação no Claude Code:

1. Baixe o ZIP da release `advogandodash-para-advos-v0.1.0` ou clone o repositório.
2. Copie a pasta `advogandodash-para-advos` para `~/.claude/skills/`.
3. Confira se existe `~/.claude/skills/advogandodash-para-advos/SKILL.md`.
4. Abra uma conversa nova e peça: “Use a skill advogandodash-para-advos para preparar a migração do meu escritório. Comece pela fase 0.”

A pasta de trabalho da migração (`~/migracao-advos`) guarda dados de clientes e fica fora de qualquer pasta sincronizada. Nada é gravado no AdvOS sem a aprovação da responsável para cada lote. Contratos e financeiro ainda não migram: viram pendência.

## Atualizações

A fonte distribuída deve ser o repositório GitHub da skill. O ZIP é um retrato de uma versão; quem o instalou precisa baixar outra versão ou atualizar o clone para receber mudanças. Mantenha `SKILL.md` e `CHANGELOG.md` na mesma revisão. Revise cada alteração antes de publicar: um achado de um escritório pode não servir para os demais.

Você pode abrir outra tarefa ou aba para investigar o AdvOS. Peça que a tarefa registre passos, evidência e proposta de mudança. Depois, revise e incorpore a mudança no repositório da skill, aumente a versão e distribua a atualização. As tarefas não sincronizam automaticamente a instrução instalada em outras contas.

## Limites

O fluxo real depende da versão do AdvOS, das permissões e das integrações de cada organização. Siga as instruções da sua equipe para atendimento jurídico, tratamento de documentos e encaminhamento. Não cole senhas ou dados pessoais em pedidos públicos de suporte.
