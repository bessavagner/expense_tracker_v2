# 007 — Anexar várias imagens (encartar antes de enviar) no chat

> Data: 2026-06-22
> Feature: permitir selecionar/anexar imagens na mensagem do chatbot **antes** de
> enviar (estilo ChatGPT/Claude web — miniaturas, remover/adicionar, texto junto),
> em vez do envio imediato atual.

## 1. Objetivo e escopo

Hoje o clipe de papel (`ChatWidget.tsx`) **envia a imagem no instante em que ela é
escolhida** (`handleImagePick → sendMultipart`), uma por vez, sem chance de digitar
texto ou pré-visualizar. Este trabalho muda o fluxo para **encartar (stage)** os
anexos: as fotos viram miniaturas acima do input; o usuário digita um texto opcional,
remove/adiciona fotos e só então **Enviar** manda tudo numa única mensagem.

### Decisões de escopo (confirmadas com o usuário)

- **Várias imagens por mensagem** (galeria), não só uma.
- As várias imagens são **páginas/ângulos do MESMO recibo** (cupom longo dividido em
  2–3 fotos, frente/verso). Vão juntas para **uma única extração → uma confirmação**.
- Toda imagem anexada continua sendo tratada como **recibo/cupom**; o **texto digitado
  guia a leitura** (ex.: "separe a roupa", "isso é mercado"). Sem visão de propósito
  geral.

### Fora de escopo (YAGNI)

- Recibos **diferentes** em lote (cada foto um recibo distinto, com fila de
  confirmações).
- Imagens não-recibo (assistente comentando imagem qualquer).
- Persistir os **bytes** das imagens no histórico do servidor.

## 2. Transporte

Multipart com o campo `image` **repetido** (um por foto) + `message` (legenda) —
reaproveita o pipeline multipart atual. Sem base64/JSON. O backend lê
`request.FILES.getlist("image")`.

## 3. Frontend — `src/backend/frontend/src/cards/ChatWidget.tsx`

- **Estado novo**: `attachments: { id: string; file: File; url: string }[]`, onde
  `url = URL.createObjectURL(file)` para a miniatura.
- File inputs (`fileInputRef`, `cameraInputRef`) ganham `multiple` no input de
  arquivo; `handleImagePick` **acumula** os arquivos escolhidos em `attachments` em
  vez de enviar. A câmera adiciona 1 por vez (capture é single).
- **Faixa de miniaturas** renderizada acima da linha do input quando
  `attachments.length > 0`: cada miniatura com botão **✕** para remover. `URL.revokeObjectURL`
  ao remover um anexo e ao limpar tudo após o envio (evitar vazamento de memória).
- **Enviar**:
  - se `attachments.length > 0` → monta `FormData` com **todas** as imagens
    (`form.append("image", file)` por anexo) + `message` (texto do input) → fluxo
    multipart (`sendMultipart`).
  - senão → fluxo texto-puro JSON, como hoje.
  - Botão de enviar habilita com **texto OU anexos** (hoje só com texto).
- **Limite** de imagens no front espelhando o backend (`MAX_IMAGES = 5`): ao exceder,
  ignora o excedente (e idealmente sinaliza). Clipe/anexar **desabilitado durante
  streaming**.
- **Balão do usuário**: `Message` ganha `images?: string[]` (object URLs). A mensagem
  recém-enviada mostra as miniaturas no balão **durante a sessão**. Histórico
  recarregado do servidor mostra apenas o rótulo-texto (as imagens não são
  persistidas) — comportamento aceito.
- Rótulo placeholder do balão enquanto envia: `📷 N foto(s)…`.

## 4. Backend

### 4.1 `src/backend/assistant/agents/extraction.py`

- `extract_receipt(images: list[tuple[bytes, str]]) -> ReceiptExtraction`: troca o
  parâmetro único `(data, media_type)` por uma **lista** de `(bytes, media_type)`.
  Monta um único run: `[EXTRACTION_INSTRUCTION, BinaryContent(d0, m0),
  BinaryContent(d1, m1), …]`.
- `EXTRACTION_INSTRUCTION` ganha uma frase: *"As imagens, quando houver mais de uma,
  são páginas/ângulos do MESMO recibo; combine-as numa única leitura, sem duplicar
  itens."*
- `ReceiptExtraction`, `receipt_needs_review`, `extraction_to_prompt` ficam iguais
  (uma extração combinada).

### 4.2 `src/backend/assistant/views.py`

- `_handle_multipart`: usa `images = request.FILES.getlist("image")` (lista). Mantém
  a exclusão mútua áudio×imagem. Se houver imagens → `_handle_images`.
- `_handle_image` → `_handle_images(request, user, images, caption)`:
  - valida **contagem** contra nova setting `ASSISTANT_MAX_IMAGES` (default 5) → 400 se
    exceder;
  - para **cada** imagem: valida tamanho (`ASSISTANT_MAX_IMAGE_MB`) e tipo
    (`ASSISTANT_ALLOWED_IMAGE_TYPES`); 400 na primeira inválida;
  - pré-processa **cada uma** com `prepare_receipt_image` → lista `prepared:
    list[(bytes, media_type)]`;
  - rótulo do usuário: `📷 [N fotos] {caption}` (ou `📷 [foto] …` quando N=1, mantendo
    o texto atual);
  - `extract_receipt(prepared)` (uma extração combinada). Persiste **um**
    `ReceiptDraft`. Fase 2 igual à atual.
  - **Fallback** (extração falha): prompt do registrador recebe **todas** as imagens
    como múltiplos `BinaryContent`, com o modelo de visão.

### 4.3 `src/backend/config/settings.py`

- `ASSISTANT_MAX_IMAGES = int(os.environ.get("ASSISTANT_MAX_IMAGES", "5"))`.

## 5. Testes (TDD — não-negociável)

### Backend (`assistant/tests/`)
- N imagens (`getlist`) → **uma** chamada a `extract_receipt` com N `BinaryContent`.
- Imagem única continua passando (lista de 1) — testes existentes não quebram.
- Acima de `ASSISTANT_MAX_IMAGES` → 400.
- Imagem inválida (tipo/tamanho) entre várias → 400.
- Fallback com múltiplas imagens → prompt do registrador com N `BinaryContent`.
- Atualizar chamadores e `test_image_is_preprocessed_before_send` para a nova
  assinatura de `extract_receipt` (cada imagem passa por `prepare_receipt_image`).

### Frontend
- Escolher imagens **acumula** em `attachments` (não envia).
- Remover miniatura tira do staging e revoga a URL.
- Enviar com anexos → multipart com N campos `image` + `message`; staging limpo após.
- Botão Enviar habilita com anexos mesmo sem texto.

## 6. Sequência sugerida

1. Backend: `extract_receipt` multi-imagem + `_handle_images` + setting + testes.
2. Frontend: estado de staging, faixa de miniaturas, envio multipart múltiplo + testes.
3. Rebuild dos artefatos de front (mount.js + tailwind.css) e commit
   (ver memória *Frontend build artifacts*).
