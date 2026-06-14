---
source_url: https://unstract.com/blog/unstract-receipt-ocr-scanner-api/ ; https://arxiv.org/html/2509.04469v1
fetched_at: 2026-06-14
publisher: Unstract / arXiv 2509.04469 (via WebSearch)
used_for: Etapa 1 — comportamento 1 (registro prático e rápido) e parsing de linguagem natural
---

# Registro conversacional de despesas / parsing por LLM (2026)

## Achados
- LLMs processam texto não-estruturado de recibos e categorizam em formato estruturado via NLU,
  **sem templates rígidos** por tipo de recibo — toleram variação de formato.
- Vantagens vs. OCR tradicional: melhor com imperfeições (amassados/borrões), parsing
  **consciente de contexto** (itens, totais, impostos), menos manutenção de workflows.
- LLMs multimodais 2026 fazem parsing visual com entendimento de layout. Gemini 2.5 Pro:
  acurácia **87,46%–96,50%** em datasets de recibos/notas.

## Aplicação ao Expense Tracker
- O registro por chat (comportamento 1) deve usar o LLM para extrair campos de mensagens livres
  em pt-BR (ex.: "mercado 80 pila no pix ontem") → data, valor, descrição, categoria, forma de
  pagamento, parcelas.
- Inferência de campos faltantes (data=hoje, categoria pela descrição) com **memória de
  correções** (já há `MemoryRule` + busca semântica pgvector).
- Suporte multimodal de recibo (imagem) é uma extensão futura possível, mas a migração atual é
  texto/chat — alinhar com o estado do projeto (foco em texto agora).
- Regras do legado a refletir no prompt: colapsar itens do mesmo estabelecimento numa linha;
  cigarro→Álcool; refrigerante→Lanche; parcelado→tabela de parcelamentos; reembolso=valor
  negativo; não inventar dados; vírgula→hífen na descrição (CSV); perguntar quando ambíguo,
  pular confirmação quando completo e inequívoco.
