# Aprimoramentos no frontend

Alguns ajustes precisam ser feitos antes de seguirmos com os próximos passos para o mobile app.

1. Dashboard:

* Usar menu hamburguer ao invés de dropdown (jogar o título "Expense Tracker" pra dentro do menu)
* Remover o elemento aside: o balão do chat deve estar no canto inferior da tela e "por cima dos elementos". Ele deve ser opaco e o ícone deve ser um robô.
* Remover o botão de "Nova Entrada", e trocar por um botão semelhante ao balão chat, ao lado deste, com ícone "+". Tanto o balão de chat quando de nova entrada devem ser grandes no desktop view.
* Os select de mês e ano estáo curtos, mesmo em desktop quase não dá pra perceber. Aumente-os.

2. Entradas

* A seleção de mês/ano deve ser igual a do dashboard.
* As tabelas em mobile view estão vazando pro lado. É preciso deixá-las responsivas.
* Preicamos de um sistema de busca para lançamentos e parcelamentos.
* Renda e vencimento do mês devem vir ao final. As primeiras tabelas devem ser lançamento e parcelamentos. O formulário de adicionar lançamentos deve vir no topo, e responsivo, assim como o resumo.
*  Os balões de chat e adicionar entrava devem persistir aqui (e nos outros menus).

3. Consolidade

* Adicionar animação da tabela fazer leve/lento scroll para centralizar no mês atual.
* Fazer a linha total estar sempre vizível (fixed? sticky?), opaca.
* Diminuir a largura do select de ano.


4. Configurações

* Refletir a responsividade do formulário de Renda nos outros menus.
* Corrigir as responsividades das entradas.
* Adicione botão de edição e salvamento das entradas (ao clicar em editar, abrir modal).

