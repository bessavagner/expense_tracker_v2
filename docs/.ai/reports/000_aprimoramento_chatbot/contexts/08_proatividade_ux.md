---
source_url: https://dl.acm.org/doi/10.1145/3706598.3713357 ; https://arxiv.org/html/2509.09309v1 ; https://www.infracost.io/glossary/budget-alerts/ ; https://uxcam.com/blog/push-notification-guide/
fetched_at: 2026-06-14
publisher: CHI 2025 (ACM) / arXiv 2509.09309 / Infracost / UXCam (via subagente de pesquisa)
used_for: Etapa 1/2/3 — comportamento 4 (interação proativa) com design que não irrita
---

# Interação proativa — design baseado em evidência (2025-2026)

- **Proatividade mal-cronometrada tem efeito reverso.** Pesquisa CHI 2025 / estudos de campo: ajuda
  proativa é frequentemente percebida como "distrativa/irritante", muitas vezes não é usada, e
  timing ruim **corrói a confiança** ao quebrar a coerência da tarefa. Pode até parecer "ameaçador".
- **Limiares em camadas, espaçados.** Prática de governança de custo: aviso cedo ~50%, urgente ~90%,
  + um empurrão pré-estouro. Trade-off explícito: limiares grossos (75/100/125) reduzem fadiga mas
  perdem anomalias de faixa média; finos pegam mais mas arriscam fadiga. → **limiares por categoria,
  ajustáveis pelo usuário.**
- **Regras que funcionam**: acionar por **contexto/fricção**, não por relógio; toda trigger precisa
  de **regra de prioridade** ("uma mensagem bem cronometrada vence uma pilha de interrupções"); ser
  transparente; dar controle ao usuário. Fadiga de notificação é real (71% desinstalam apps por push).

## Modelo prático (recomendado)
1. **Motor de regras determinístico** dispara eventos candidatos (% do teto, anomalia, conta
   recorrente a vencer) — calculado em código (Etapa 2), **não** no LLM.
2. **Gate de prioridade/dedup** suprime eventos de baixo valor ou recém-enviados.
3. Só então o **LLM formula a mensagem** (Etapa 3).

## Alinhamento com o legado
O sistema legado sheets+claude prega "silêncio" — não enviar comentários/observações não
solicitados. → Proatividade deve ser **acionada por evento** (ex.: ao registrar um gasto que cruza
um limiar) e **opcional/ajustável**, nunca a cada mensagem. Compatibiliza "proativo" com "bookkeeper
silencioso".
