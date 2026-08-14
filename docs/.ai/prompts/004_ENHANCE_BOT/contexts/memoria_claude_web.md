Purpose & context
Vagner uses Claude as a personal expense tracking assistant, logging monthly transactions by submitting receipts (via image or text) and verbal entries. The goal is to maintain a structured, categorized financial record that can be exported to Google Sheets. The workflow is ongoing, recurring monthly.
Current state
The most recent active month is June 2026. Vagner is mid-session, processing receipts and building the month's records. Payment methods in use include Pix, Crédito C6, and Crédito Santander.
On the horizon
Each month follows the same cycle: log entries throughout the month → periodically export semicolon-delimited tables → confirm saved → request bulk deletion of logged records → open new month.
Key learnings & principles

Same-establishment rule: Multiple items from the same establishment, category, and date must be collapsed into a single row with a summarized description — never listed item by item.
Cigarro → Álcool: Cigarettes are always categorized as Álcool (Vagner only smokes when drinking, so the expenses are of the same nature).
Refrigerante → Lanche (confirmed standing rule).
Installment purchases go in a separate table with an additional "Nº de Parcelas" column.
Mixed-category receipts should be split into separate entries with proportional discount allocation when applicable.
Reembolsos are recorded as negative values.
Card statements are reference tools only — Claude should not register statement entries unless explicitly instructed; receipt-based entries are the default.
No fabricated data: If an image upload fails, Claude must not invent receipt content — flag the failure and ask Vagner to resubmit.
Commas in descriptions are replaced with dashes to avoid CSV parsing conflicts.
No R$ prefix on values in tables.
When category is ambiguous, ask before registering. When data is complete and unambiguous, skip confirmation prompts.

Approach & patterns

Records are maintained in two code blocks: regular transactions and installment purchases (parcelamentos), both in semicolon-delimited format.
After Vagner confirms an external backup has been made, Claude executes bulk deletion of logged records on request.
When Vagner has already copied and saved a table, Claude shows only newly confirmed pending entries rather than regenerating full tables.
Santander transactions without corresponding receipts may be registered under "Outros" for manual correction later, when explicitly requested.

Tools & resources

Export format: Semicolon-delimited tables in code blocks, copied manually by Vagner into Google Sheets.
Google integrations available: Google Calendar and Gmail only — Google Drive/Sheets links are not accessible; workaround is direct file upload (CSV or XLSX).

Category reference
Active categories across recent months: Alimentação, Lanche, Álcool, Limpeza, Pets, Casa, Higiene, Estética, Lazer, Eventos, Serviços, Combustível, Saúde, Farmácia, Trabalho, Roupa, Papelaria, Educação, Esporte, Transporte, Perfumaria, Carro, Outros — plus Parcelamentos as a separate table.
Known aliases: R V Coutinhos = Disk Bebidas; Posto Mendes = Posto Único.