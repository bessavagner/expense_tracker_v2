# Expense tracker: um sistema de registro e acompanhamento do financeiro pessoal ou familiar


Eu uso tabelas em Google Sheets para registro e gastos e acompanhamento do saldo. Em [docs/prompts/SETUP/context](context) há amostras de entradas de dados e view. As entradas são apenas registros comuns ou parcelamentos. Idealmente devemos usar o mesmo modelo para ambos.

## Project Scaffold

Você deverá usar nosso gerador de projetos em [/home/bessa/Documents/trabalhos/project_generator](project_generator).

## Must haves

* AI Assistant: multi assistente com orquestrador   
* Frontend escalável de baixa manutenção mas com poderosas ferramentas de visualização.
* Django + server adequado para Google Cloud Run.
* Postgres (docker/dev) + supabase (prod).

## Behavior Driven Design

Construa o setup deste projeto tenho como fundamento o BDD: as specs devem ser escritas com base nos comportamentos experados abaixo:

### Entradas e consultas

* Principal interface de input deve ser o chat de Assistente de IA: texto, imagem, audio, arquivo, foto, etc. O assistente deve inferir.
* Igualmente ao input, o chat deve ser a principal via para querries de visualizações, resumos, tendências ou outras métricas, medidas e experimentos econométricos, financeiros e de análise de dados e previsões. As visualizações devem ter telas/view/modais próprios, e são abertos assim que o assistente produzir o conteúdo solicitado.
* O assistente deve inferir informações não apresentadas, mas abaixo de um threshold de confiança, deve conferir com o usuário.
* Entradas repetidas ou correções feitas pelo usuário deve ser salvo em memória: sim o assistente de ia deve ter um sistema de memória otimizado para este caso. Pesquise no github e na documentação do pydantic ai quais as melhores opções atualmente.
* Mas o usuário pode entrar com um registro manualmente.

### Telas

* O chat deve ser um wdiget fixável. Todas as telas devem dar conta de serem hamônicas com o chat fixado.
* Depois do chat, a tela principal é um dashboard com métricas, medidas, e informações de destaques de período mensal e semanal.
* Um tela deve ser dedidaga à visualização de entradas de cada mês, uma aba para cada mês do ano selecionado.
* Outras telas devem: mostra o consolidado por categorias de gastos diversos, consolidado por categorias de parcelados, etc.
* Uma tela de configuração deve permitir o usuário inputar renda mensal (o período padrão é indeterminado, mas é possível selecionar um período finito ou ser apenas de um único mês), configurar novas formas de pagamentos (por hora apenas pix ou cartão de crédito, como estão nas amostras); cartões de crédito devem ter os dias de fechamento, pois gastos diversos ou parcelados a partir desse dia são contabilizados como entrada do mês seguinte. Note que na tabela de parcelamentos, as datas de entrada são de início do mês, mas o novo sistema deve dar conta de quando a entrada parcelada vai ser contabilizada com base na data da compra e na data de fechamento da fatura.

## Test Driven Design

Absolutamente todo o desenvolvimento desse projeto deve ter como o maior princípio de todos o desenvolvimento por meio de testes: nenhuma feature deve ser comitada sem toda a cobertura de testes necessárias. O ambiente de teste deve ser o container. Cada desenvolvimento deve ser inciado com testes falhos. Erros e falhas nos testes devem motivar a revisão no código fonte. Priorise-se verificar o código fonte antes de verificar se falhas ou erros são culpa dos testes.

## Worktrees

Todo novo desenvolvimento deve ser feito em um worktree separado. O merge para main deve ocorrer apenas após todos os testes passarem com sucesso. Caso o code quality bloqueie o merge, isso signfica que o desenvolvimento não encerrou: code quality é lei para o desenvolvimento deste projeto

## Code Quality

Merge para main e push para remote main devem ser bloqueados pelo mais duros padrões de code quality.