# Model evaluation (E08)

Generated: 2026-08-15T08:03:32-03:00

## Extraction

| Model | n | Score | amount_accuracy | category_accuracy | date_accuracy | item_precision | item_recall | money_ok_rate | store_accuracy | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `pipeline(openai:gpt-5.6-luna -> openai:gpt-5.4)` | 15 | 0.69 | 0.90 | 0.90 | 1.00 | 0.96 | 0.98 | 0.73 | 0.80 | 213163 | 14916 | 0.104560 | 8129 |

### `pipeline(openai:gpt-5.6-luna -> openai:gpt-5.4)` — what it got wrong

- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- compensa-2026-05-12: missed 1, spurious 1
- cosmos-2026-06-03: partial
- cosmos-2026-06-19: missed 2, spurious 2
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: missed 1, spurious 9
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED
