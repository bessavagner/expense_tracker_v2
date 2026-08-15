# Model evaluation (E08)

Generated: 2026-08-15T06:57:40-03:00

## Behaviour

| Model | n | Score | cases_passed | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|
| `openai:gpt-5.4` | 7 | 0.86 | 6.00 | 172636 | 1838 | 0.459160 | 3818 |

### `openai:gpt-5.4` — what it got wrong

- billing-month-after-closing-day: no row satisfied Alimentacao (no rows left); ledger total 0 != expected 120.00
