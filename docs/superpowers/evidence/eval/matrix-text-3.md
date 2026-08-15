# Model evaluation (E08)

Generated: 2026-08-15T07:49:49-03:00

## Behaviour

| Model | n | Score | cases_passed | In tok | Out tok | USD | Avg ms |
|---|---|---|---|---|---|---|---|
| `openai:gpt-5.4-mini` | 7 | 0.86 | 6.00 | 176399 | 1770 | 0.140264 | 2930 |
| `openai:gpt-5.6-luna` | 7 | 0.86 | 6.00 | 184017 | 1623 | 0.038751 | 3905 |

### `openai:gpt-5.4-mini` — what it got wrong

- americanas-split-on-request: no row satisfied Roupa (no rows left); no row satisfied Lanche (no rows left); ledger total 0 != expected 42.16

### `openai:gpt-5.6-luna` — what it got wrong

- americanas-split-on-request: ModelHTTPError: status_code: 400, model_name: gpt-5.6-luna, body: {'message': "Invalid value for 'content': expected a string, got null.", 'type': 'invalid_request_error', 'param': 'messages.[19].content', 'code': None}
