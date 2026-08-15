# Model evaluation (E08)

Generated: 2026-08-15T07:38:11-03:00

## Extraction

| Model | n | Score | amount_accuracy | category_accuracy | date_accuracy | item_precision | item_recall | money_ok_rate | store_accuracy | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai:gpt-5.4-mini` | 15 | 0.71 | 0.99 | 0.90 | 1.00 | 0.99 | 1.00 | 0.73 | 0.93 | 109097 | 15011 | 0.149372 | 7831 |
| `openai-responses:gpt-5.6-terra` | 15 | 0.58 | 0.97 | 0.81 | 1.00 | 0.99 | 1.00 | 0.60 | 1.00 | 201582 | 14971 | 0.582816 | 10291 |
| `openai:gpt-5.6-luna` | 15 | 0.58 | 0.89 | 0.90 | 1.00 | 0.97 | 0.98 | 0.60 | 0.87 | 188482 | 10200 | 0.049936 | 6892 |

### `openai:gpt-5.6-luna` — what it got wrong

- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- compensa-2026-05-12: money invariant FAILED, missed 2, spurious 1
- cosmos-2026-06-03: money invariant FAILED
- cosmos-2026-06-19: missed 1, spurious 1
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
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
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED

### `openai-responses:gpt-5.6-terra` — what it got wrong

- americanas-2026-06-12: money invariant FAILED
- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- cosmos-2026-06-03: money invariant FAILED
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED
