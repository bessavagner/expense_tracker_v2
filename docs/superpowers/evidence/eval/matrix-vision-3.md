# Model evaluation (E08)

Generated: 2026-08-15T07:44:19-03:00

## Extraction

| Model | n | Score | amount_accuracy | category_accuracy | date_accuracy | item_precision | item_recall | money_ok_rate | store_accuracy | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai:gpt-5.4-mini` | 15 | 0.65 | 0.98 | 0.92 | 1.00 | 0.99 | 1.00 | 0.67 | 0.93 | 99345 | 13988 | 0.137454 | 7542 |
| `openai-responses:gpt-5.6-terra` | 15 | 0.64 | 0.98 | 0.85 | 0.93 | 0.99 | 1.00 | 0.67 | 1.00 | 201582 | 14360 | 0.575484 | 9539 |
| `openai:gpt-5.6-luna` | 15 | 0.38 | 0.87 | 0.84 | 1.00 | 0.96 | 0.97 | 0.40 | 0.87 | 191324 | 11383 | 0.051924 | 7348 |

### `openai:gpt-5.6-luna` — what it got wrong

- americanas-2026-06-12: money invariant FAILED
- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- compensa-2026-05-12: money invariant FAILED, missed 2, spurious 1
- cosmos-2026-06-03: money invariant FAILED
- cosmos-2026-06-19: missed 2, spurious 2
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: money invariant FAILED, spurious 8
- hipernacional-2026-06-19: money invariant FAILED
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED

### `openai:gpt-5.4-mini` — what it got wrong

- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- cosmos-2026-06-03: partial
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: money invariant FAILED
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED

### `openai-responses:gpt-5.6-terra` — what it got wrong

- americanas-2026-06-12: partial
- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- cosmos-2026-06-03: money invariant FAILED
- cosmos-2026-06-19: partial
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED
