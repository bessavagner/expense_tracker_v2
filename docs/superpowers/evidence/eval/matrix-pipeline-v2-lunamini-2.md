# Model evaluation (E08)

Generated: 2026-08-15T08:12:38-03:00

## Extraction

| Model | n | Score | amount_accuracy | category_accuracy | date_accuracy | item_precision | item_recall | money_ok_rate | store_accuracy | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `pipeline(openai:gpt-5.6-luna -> openai:gpt-5.4-mini)` | 15 | 0.75 | 0.86 | 0.84 | 1.00 | 0.98 | 0.99 | 0.80 | 0.93 | 229185 | 16736 | 0.104040 | 7371 |

### `pipeline(openai:gpt-5.6-luna -> openai:gpt-5.4-mini)` — what it got wrong

- americanas-2026-06-12: partial
- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- cosmos-2026-06-03: partial
- cosmos-2026-06-19: missed 1, spurious 1
- drogasil-2026-07-04: partial
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED
