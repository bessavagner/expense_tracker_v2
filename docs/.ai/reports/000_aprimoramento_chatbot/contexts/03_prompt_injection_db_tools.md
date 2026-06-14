---
source_url: https://cygeniq.ai/blog/prompt-injection-attacks-risks-and-preventions/ ; https://witness.ai/blog/prompt-injection/ ; https://www.vectra.ai/topics/prompt-injection ; https://arxiv.org/html/2504.19793v2
fetched_at: 2026-06-14
publisher: CygenIQ / Witness.ai / Vectra.ai / arXiv 2504.19793 (via WebSearch)
used_for: Etapa 3 — segurança dos agentes que escrevem no DB financeiro; gates de confirmação
---

# Defesa contra prompt injection em agentes com ferramentas de escrita

## Panorama de ameaça (2026)
- Ataques de prompt injection cresceram **340% em 2026** (OWASP 2026 LLM Security Report) — a
  categoria de ciberataque que mais cresce.
- Superfície ampliada quando agentes ganham capacidades reais: acessar DB, executar código,
  enviar mensagens, mover dinheiro. Risco concreto: enganar o agente para registrar/alterar
  dados errados.

## Defesa em profundidade (camadas que se sobrepõem)
1. **Privilégio mínimo (deny by default)**: o agente só tem as ferramentas necessárias; ações de
   alto risco exigem **aprovação humana** (no nosso caso: deletar/editar registros, mudar teto,
   mudar renda).
2. **Separação de instruções vs. conteúdo não-confiável**: delimitar claramente o input do
   usuário; usar templates "endurecidos".
3. **Filtragem de input**: considerar texto oculto/ofuscação.
4. **Validação de output**: schemas estritos + allowlist de tool-calls.

## Limites das defesas atuais
- Defesas de prevenção (StruQ, SecAlign) e de detecção são **insuficientes** isoladamente; nem
  modelos de fronteira ficam imunes. → **Defesa em profundidade é a única estratégia viável**.

## Aplicação ao Expense Tracker
- Os tools de escrita já retornam mensagens de erro tipadas e validam categoria/forma de
  pagamento — manter e endurecer.
- **Gates de confirmação obrigatórios** para: criar/editar/excluir lançamento, criar categoria,
  mudar teto, atualizar renda, definir gasto sistemático (já parcialmente no prompt atual).
- **Nunca** delegar exclusão por chat sem confirmação explícita (espelha a regra do legado).
- Sub-agentes só recebem ferramentas do seu escopo (registrador não consulta nada destrutivo;
  analista/planejador são **read-only**).
- Toda escrita escopada por `user=ctx.deps` (isolamento por usuário) — já é o caso.
