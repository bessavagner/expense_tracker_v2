# Aprimorar Chat Bot

Estou na fase de migrar os dados do google sheets para supabase e uso do Claude web para o uso do chat bot do expense tracker.

A migração dos dados já está quase completa, e vou concluí-la depois. Agora, falta apenas aprimorar o chat bot para que ele tenha recursos e comportamentos robustos no registro de dados, criação de reports e análise de dados, e query de dados.

## Contextos

Em ./contexts estão em arquivos os dados que extraí do meu claude web. Não precisa usá-los as is, pois aqui no expense tracker há algumas diferenças sobre esse meu sistema legado sheets+claude. Mas que sirvam de inspiração para as instruções dos bots.

## Tarefas

Vamos fazer um update do bot do expense tracker. Queremos que ele tenha os comportamentos:

1. Registro Prático e Rápido
2. Organização e Análise de Dados
3. Planejamento e Inteligência Financeira
4. Interação Proativa

Faça esse update em pelo menos três etapas:

1. Aprimoramento do bot atual com prompts que melhor reflitam o sistema legado sheets+claude.
2. Atualização do backend com queries faltantes para o comportamento do novo bot.
3. Criação de um sistema de agents, com um orquestrador (modelo leve, rápido e barato) e outros agentes repsonsáveis por diferentes tarefas de diferentes complexidades, delegadas pelo orquestrador, com prompts robustos e seguros.

## Obrigatório

Uso de web search, skill research, MCP research, coleta de registro de contextos em nova pasta de um novo report (atualize este repositório para incluir as mesmas instruçẽos de report como em /home/bessa/Documents/trabalhos/RHIA/docs/.ai/REPORT_CONVENTION.md). Gere esse report, que servirão de elaboração do plano de desenvolvimento para cumprimento das tarefas aqui registradas.

Apenas começe a executar as tarefas após a escrita do plano de desenvolvimento.

Toda atualização deve ser feita em uma worktree. O merge para a main local só deve ser feito após a conclusão com sucesso de todas as tarefas.