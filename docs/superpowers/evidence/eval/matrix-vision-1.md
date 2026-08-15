# Model evaluation (E08)

Generated: 2026-08-15T07:31:53-03:00

## Extraction

| Model | n | Score | amount_accuracy | category_accuracy | date_accuracy | item_precision | item_recall | money_ok_rate | store_accuracy | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `openai:gpt-5.4-mini` | 15 | 0.70 | 0.93 | 0.90 | 1.00 | 0.99 | 1.00 | 0.73 | 0.93 | 103870 | 13982 | 0.140820 | 7816 |
| `openai-responses:gpt-5.6-terra` | 15 | 0.65 | 0.98 | 0.89 | 0.93 | 0.99 | 1.00 | 0.67 | 1.00 | 201582 | 13970 | 0.570804 | 9713 |
| `openai:gpt-5.6-luna` | 15 | 0.56 | 0.95 | 0.89 | 1.00 | 0.97 | 0.99 | 0.60 | 0.87 | 176790 | 9764 | 0.047075 | 6662 |

### `openai:gpt-5.6-luna` — what it got wrong

- americanas-2026-06-12: money invariant FAILED
- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- compensa-2026-05-12: missed 1, spurious 1
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
- drogasil-2026-07-04: partial
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: money invariant FAILED
- nobre-lar-2026-05-18: money invariant FAILED
- ultrafarma-2026-08-12: money invariant FAILED

### `openai-responses:gpt-5.6-terra` — what it got wrong

- casa-do-feijao-verde-2026-07-03: money invariant FAILED
- cosmos-2026-06-03: money invariant FAILED
- drogasil-2026-07-04: money invariant FAILED
- hipermacional-2026-06-15: spurious 8
- hipernacional-2026-06-19: partial
- hipernacional-2026-07-08: partial
- mateus-2026-06-22: partial
- nobre-lar-2026-05-18: money invariant FAILED
- pioneiro-2026-05-05: partial
- ultrafarma-2026-08-12: money invariant FAILED
