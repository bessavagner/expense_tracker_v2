---
source_url: https://kaopiz.com/en/articles/finance-ai-chatbots/ ; https://www.voiceflow.com/blog/finance-ai-chatbot ; https://useorigin.com/resources/blog/ai-in-personal-finance-2026-comparing-the-top-tools-and-approaches
fetched_at: 2026-06-14
publisher: Kaopiz / Voiceflow / Origin (via WebSearch)
used_for: Etapa 1 e 3 — comportamentos 2 (análise), 3 (planejamento) e 4 (interação proativa)
---

# Assistentes financeiros conversacionais — boas práticas (2026)

## O que a geração 2026 faz
- Evoluiu de "checar saldo + Q&A" para: **coaching de orçamento**, resolver disputas, explicar
  termos em linguagem simples, **executar ações**, gerenciar assinaturas, sinalizar atividade
  suspeita, e dar orientação personalizada.
- Feature mais valorizada: **notificação proativa**.

## Padrões de proatividade (comportamento 4)
- Clientes esperam: **alertas proativos antes de um problema** (saldo baixo, conta a vencer,
  estouro de orçamento) e conselhos personalizados que refletem o comportamento real.
- Exemplos de referência:
  - **Cleo**: gestão financeira via interface conversacional; sugestões de economia automáticas.
  - **Eno (Capital One)**: foco em alertas em tempo real e notificações proativas — "observa a
    conta em segundo plano e mostra o que você ia querer saber".
- Padrão: o bot **categoriza gastos, sinaliza estouros, gera relatórios** e envia alertas de
  contas/cartões/saldo para evitar multas e criar bons hábitos.

## Aplicação ao Expense Tracker
- **Comportamento 2 (análise)**: resumos mensais, quebra por categoria/forma de pagamento,
  relatórios — parte já existe (`query_expenses`, `query_budget_status`).
- **Comportamento 3 (planejamento)**: projeção de gasto até fim do mês, recomendação de
  orçamento, detecção precoce de estouro, metas de economia.
- **Comportamento 4 (proatividade)**: gatilhos como "você está em 90% do teto de Alimentação".
  Importante: proatividade **sob demanda/contextual**, sem virar spam — alinhado com a regra do
  legado de não enviar comentários/observações não solicitados. Proatividade deve ser opcional e
  acionada por evento (ex.: ao registrar um gasto que cruza um limiar), não a cada mensagem.
