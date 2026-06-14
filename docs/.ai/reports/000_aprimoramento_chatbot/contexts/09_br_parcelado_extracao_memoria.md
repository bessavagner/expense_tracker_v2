---
source_url: https://pocketclear.app/blog/expense-tracker-brazil.html ; https://paymentexpert.com/2025/10/07/brazils-race-to-standardise-pix-parcelado-for-further-instant-payment-growth/ ; https://agenta.ai/blog/the-guide-to-structured-outputs-and-function-calling-with-llms ; https://vectorize.io/articles/best-ai-agent-memory-systems
fetched_at: 2026-06-14
publisher: PocketClear / PaymentExpert / Agenta / Vectorize (via subagente de pesquisa)
used_for: Etapa 1/2 — contexto BR (parcelado/Pix), extração estruturada e memória de correções
---

# Brasil, extração estruturada e memória

## Contexto BR
- "Cultura do parcelamento" + Pix + inflação são os traços que definem finanças pessoais no Brasil.
- **Pix Parcelado** virou regulado (fim de out/2025). → modelar parcelado como **compra-pai + N
  parcelas-filhas com vencimentos**, permitindo projeção de fluxo de caixa de 12 meses. (O projeto
  já tem `InstallmentPlan` + `Entry.installment_plan` — alinhado.)
- Valores em Reais; exportações CSV/relatórios prontos para impostos são feature esperada.

## Extração estruturada (registro por NL)
- Padrão: **function calling + schema estrito** (Pydantic/JSON) força o modelo a emitir campos
  tipados; validar inline. Padrão neurossimbólico (extração LLM + camada simbólica de validação)
  aumenta acurácia em documentos transacionais ao impor regras de domínio pós-extração.
- Inferir data/categoria/forma de pagamento = extrair o que foi dito + default por regra/histórico +
  **expor campos inferidos** para correção.
- PydanticAI já dá tools tipadas; manter validação de categoria/forma de pagamento existente.

## Memória de correções
- Aprender com correções = **memória factual persistente** (vetorial + regras), escopada por
  usuário. Sem memória o agente re-pergunta e nunca aprende; com ela, "iFood é sempre Alimentação"
  persiste entre sessões. (O projeto já tem `MemoryRule` + `MemoryEmbedding`/pgvector — base pronta;
  reforçar criação de regra ao corrigir.)
