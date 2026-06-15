# 006 — Aprimorar a leitura de recibos/notas fiscais pelo bot

> Resposta ao prompt `006_ENHANCE_IMAGES_READING`: por que a interação falhou e como
> aprimorar a performance do bot na leitura de recibos e cupons fiscais.

## 1. O que o recibo realmente continha (cupom SAT — Americanas)

A foto (`contexts/IMG_20260612_174310143_HDR.jpg`) é **perfeitamente legível** para um
humano, apesar de estar **girada 90°**, em papel térmico de **baixo contraste** e com
uma **marca d'água rosa "americanas"** atravessando o texto:

| Item | Categoria provável | Valor |
|------|--------------------|------:|
| SOUTIEN TOP B+ TAF21 BRANCO GG | **Roupa** | 9,99 |
| BACONZITOS B&G ELMA CHIPS M | Lanche | 9,99 |
| LAYS CLASSICA B&G ELMA CHIPS M | Lanche | 9,99 |
| WAFER MAIS AMENDOIM 102G HERSHEYS | Lanche | 6,19 |
| BATATA PRINGLES CREME E CEBOLA 109G | Lanche | 9,99 |
| **Valor total** | | 46,15 |
| **Desconto** | | −3,99 |
| **Valor a pagar** | | **42,16** |

- **Loja:** `americanas sa - 1063` / CNPJ `00.776.574/1016-96` / Crateús-CE — está
  escrito **no cupom** e ainda repetido na marca d'água.
- **Forma de pagamento:** `Cartão de Crédito` (MASTERCARD CRÉDITO À VISTA).
- **Split correto:** Roupa = 9,99 · Lanche = 36,16 (antes do desconto), com o desconto
  de 3,99 a ratear.

### O que o bot produziu (de `contexts/iteraction.txt`)

1. Jogou **todos os itens em "Lanche"** (não separou a roupa).
2. Afirmou que **não conseguiu ler o nome da loja** — sendo que ele aparece duas vezes
   na imagem.
3. Após a correção do usuário, registrou **"Roupa: R$ 42,16 / Lanche: R$ 0,00"** —
   pôs o valor inteiro numa categoria e zero na outra.

A falha central não é "OCR ruim": é **arquitetural**. Os dados por item são extraídos
num turno e **descartados**, então nenhum turno seguinte consegue ratear valores.

---

## 2. Causas-raiz (com evidência no código)

### C1 — O recibo é lido pelo modelo **mais barato**, e o "escape hatch" de visão está morto
`config/settings.py:189-191` define `LLM_VISION_MODEL` com o comentário literal
*"escape hatch caso o modelo leve leia recibo mal"*. Mas **nada no código usa essa
variável** (`grep LLM_VISION_MODEL` → só a definição). O fluxo de imagem
(`views.py:229-255`) manda a foto para o `registrar_agent`, que é construído com
`settings.LLM_ORCHESTRATOR_MODEL` (`registrar.py:34-38`) = `openai:gpt-5.4-mini`
(`settings.py:171,175`). Ou seja: o cupom térmico girado e com marca d'água é lido pelo
modelo *mini*, exatamente o cenário que o autor previu e tentou contornar — mas o
contorno nunca foi ligado.

### C2 — Zero pré-processamento da imagem
`_handle_image` (`views.py:229-255`) envia os bytes crus (`BinaryContent`) — 2,7 MB,
**girados 90°**, baixo contraste, marca d'água por cima. Não há:
- correção de orientação (EXIF / autorrotação),
- downscale / normalização de contraste / grayscale,
- nenhum realce que separe a tinta da marca d'água rosa.

Modelos de visão leem muito melhor um recibo **na vertical e com bom contraste**.

### C3 — Não existe etapa de **extração estruturada**
O pipeline pede que o mesmo turno **leia (OCR) e contabilize** em texto livre. Não há
passo intermediário que devolva um JSON de itens (`descrição, qtd, unitário,
total_linha, loja, data, total, desconto, forma_pagto`). Sem os itens estruturados, o
modelo não tem como dividir categorias nem alocar valores de forma confiável — foi
isso que gerou o `R$ 0,00`.

### C4 — Não há primitiva de registro **multi-item / multi-categoria**
`register_entry` (`registrar.py:56-81`, `tools.py:60-122`) grava **uma linha**:
um valor, uma categoria, uma forma de pagamento. Para separar em duas categorias o
modelo precisaria: agrupar itens por categoria, **somar cada grupo**, **ratear o
desconto** e chamar `register_entry` N vezes — tudo de cabeça. Isso contradiz a própria
regra dos prompts (*"NÃO calcule de cabeça"*, `prompts.py:200`) e é onde o `42,16/0,00`
nasce. Falta uma ferramenta determinística que receba `[itens + categoria]` e produza
as entradas por categoria com o desconto rateado.

### C5 — O contexto da foto é **perdido** entre turnos (o pior bug)
- `_handle_image` chama o registrador com `message_history=None` (`views.py:252-255`):
  o registro por foto é **one-shot**.
- O que fica persistido em `ChatMessage` é só o rótulo `"📷 [foto enviada]"`
  (`views.py:246-249`) — **os bytes da imagem e os itens extraídos não são salvos**.
- Quando o usuário corrige ("separe as categorias, adicione a loja"), a mensagem vai
  pelo `_handle_json` → orquestrador → `delegate_registro`, que repassa **apenas a
  string** ao registrador (`orchestrator.py:39-50`). O registrador **não recebe
  histórico** (`registrar_agent.run(request, ...)`), então roda **cego**: sabe só o
  total 42,16, sem os preços por item. Resultado inevitável: tudo em Roupa, zero em
  Lanche.

Em resumo: mesmo com OCR perfeito, a arquitetura atual **não consegue** corrigir um
split depois, porque os dados por item nunca sobrevivem ao primeiro turno.

### C6 — Tensão nos prompts + resumo não verificável
`PHOTO_POLICY`/`LEGACY_REGISTRO_RULES` (`prompts.py:73-99,126-136`) mandam *"colapsar
itens do mesmo estabelecimento em UMA linha"*, e o modelo super-aplicou isso (uma linha
só). A regra real é colapsar por **estabelecimento + categoria + data** — a separação
por categoria não está enfatizada no fluxo de foto. Além disso, o resumo de confirmação
mostra **um valor agregado**, não uma tabela item→categoria→valor, então o usuário não
consegue verificar o rateio antes de gravar.

---

## 3. Recomendações priorizadas

### P0 — Ganhos imediatos, baixo esforço

1. **Ligar o `LLM_VISION_MODEL` (corrigir o escape hatch morto).**
   Construir o agente que lê a foto com `settings.LLM_VISION_MODEL` em vez de
   `LLM_ORCHESTRATOR_MODEL`, e definir o default para um modelo de visão forte
   (ex.: `openai:gpt-5.4` / equivalente multimodal capaz), mantendo o override por env.
   *Arquivos:* `views.py:_handle_image`, `registrar.py:34`. *Esforço:* ~1 h.

2. **Pré-processar a imagem antes de enviar** (Pillow, já no stack Django):
   autorrotação por EXIF + heurística de orientação, downscale para o lado maior
   ~1600–2000 px, conversão para grayscale e aumento de contraste/binarização leve.
   Ajuda diretamente com a marca d'água rosa e o papel térmico.
   *Arquivo:* novo `assistant/services/image_prep.py`, chamado em `_handle_image`.
   *Esforço:* meio dia.

3. **Forçar a separação por categoria no prompt de foto** e exigir um **resumo em
   tabela item→categoria→valor** antes de gravar (não um total agregado). Deixar
   explícito: colapsar é por *estabelecimento+categoria+data*, e **a soma das linhas
   tem de bater com o valor pago**. *Arquivo:* `prompts.py:PHOTO_POLICY`.
   *Esforço:* ~2 h.

### P1 — Correção estrutural (resolve o `R$ 0,00` de verdade)

4. **Extração estruturada em duas fases.** Fase 1 (visão): devolver JSON validado por
   Pydantic — `loja, cnpj, data, itens[{descrição, qtd, unitário, total_linha}],
   total, desconto, forma_pagamento`. Fase 2 (contábil): mapear cada item para
   categoria (com `check_memory`) e **só então** confirmar. Usar `result_type` /
   structured output do PydanticAI garante números reais, não estimados.
   *Esforço:* 1–2 dias.

5. **Persistir o recibo extraído (resolve C5).** Salvar o JSON estruturado anexado à
   `ChatMessage` da foto (campo JSON ou tabela `ReceiptDraft`). Assim o turno de
   correção tem os preços por item, e o registrador deixa de rodar cego. Acompanha:
   o `delegate_registro` precisa repassar/recuperar esse rascunho (hoje só passa uma
   string — `orchestrator.py:39-50`). *Esforço:* 1 dia.

6. **Ferramenta de registro multi-categoria com rateio determinístico.** Nova tool
   `register_receipt(items_by_category, discount, payment_method, date, store)` que
   soma cada grupo e **rateia o desconto proporcionalmente** em Python (não no LLM),
   gravando N entradas atômicas. Elimina a aritmética de cabeça que produziu o
   `42,16/0,00`. *Arquivo:* `tools.py` + `registrar.py`. *Esforço:* 1 dia.

### P2 — Robustez e qualidade contínua

7. **Caminho QR/SAT.** O cupom traz um QR para `sefaz.ce.gov.br` e a chave de acesso.
   Quando legível, ler a NFC-e oficial dá os itens com **100% de precisão** — bypassa o
   OCR inteiro. Vale como melhoria futura (decodificar QR com `pyzbar`/`opencv`).

8. **Suíte de regressão de visão.** Guardar um punhado de fotos reais (esta inclusa)
   como fixtures e testar a extração estruturada contra um gabarito (loja, itens,
   total, desconto). Hoje não há teste cobrindo leitura de imagem.
   *Arquivo:* `assistant/tests/test_image_extraction.py`.

9. **Fallback explícito de baixa confiança.** Se a confiança da extração for baixa ou a
   soma dos itens não bater com o total, mostrar a tabela e pedir confirmação campo a
   campo — em vez de "não consegui ler" (que aqui foi falso) ou de chutar `0,00`.

---

## 4. Sequência sugerida

`P0.1 + P0.2 + P0.3` numa primeira PR (alto impacto, baixo risco — provavelmente já
teria lido a loja e separado a roupa neste caso). Depois `P1.4 → P1.5 → P1.6` como a
correção estrutural que torna o rateio e a correção multi-turno **corretos por
construção**. `P2` conforme houver fôlego.

## 5. Resumo executivo

A interação falhou por **três defeitos concretos**, não por "IA fraca":
(1) o recibo é lido pelo modelo mini porque `LLM_VISION_MODEL` está definido mas
**nunca é usado**; (2) **nenhum pré-processamento** da imagem girada/desbotada; e
(3) os **itens extraídos não sobrevivem ao primeiro turno**, então separar categorias e
ratear valores depois é impossível — daí o `Roupa R$42,16 / Lanche R$0,00`. As três têm
correção direta e estão priorizadas acima.
