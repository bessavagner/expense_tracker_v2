# Design: entrada multimodal (áudio + foto) → registros

- **Data:** 2026-06-14
- **Autor:** Vagner Bessa (+ Claude Code)
- **Status:** aprovado (design) — pendente plano de implementação
- **Contexto:** continuação do prompt 004 (aprimoramento do chat bot). Hoje o
  `ChatWidget` só envia texto. Esta feature adiciona **áudio (nota de voz)** e
  **foto (recibo/câmera/galeria)** como fonte de entradas de registros.

## TL;DR

O `ChatWidget` ganha dois botões: 🎤 (gravar voz) e 📷 (câmera/galeria). A mídia
é enviada por `multipart/form-data` ao **mesmo** endpoint `/chat/`, processada
**em memória e descartada** (nada salvo em disco/Supabase) e transformada em
lançamento(s) pelo agente **Registrador**, reaproveitando as regras-legado que
ele já aplica. Áudio é transcrito pela **API da OpenAI** e segue pelo
orquestrador (router decide registrar vs. perguntar); imagem vai **direto ao
Registrador** com `BinaryContent` (recibo = registro). A resposta volta pelo
**mesmo stream SSE** de hoje.

## Decisões aprovadas

1. **Transcrição:** somente **OpenAI API** (sem Whisper local). Sem novas chaves
   — reusa `LLM_API_KEY`/`OPENAI_API_KEY` já configurada.
2. **Persistência:** **processar e descartar**. `ChatMessage` guarda apenas o
   texto resultante (transcrição/legenda); a mídia nunca é persistida.
3. **Captura:** gravar voz na hora (MediaRecorder) **+** câmera/galeria (`input
   file` com `accept="image/*"` `capture="environment"`).
4. **Roteamento:** áudio → texto → **orquestrador**; imagem → **Registrador**
   direto.
5. **Limite:** **1 arquivo por mensagem** (áudio **ou** imagem) + legenda de
   texto opcional.

## Escopo e princípio

Mídia é **fonte de registro**. O caminho de texto atual permanece **intacto**
(regressão obrigatória). Nada de storage, anexo de comprovante, histórico visual
de mídia, Whisper local ou múltiplos arquivos por mensagem (YAGNI).

## Fluxo

```
ChatWidget
  ├─ 🎤 grava voz (MediaRecorder → audio/webm)  ─┐
  └─ 📷 câmera/galeria (input file)              ─┤ multipart/form-data
                                                  ▼
POST /chat/   (mesmo endpoint; aceita JSON OU multipart)
  ├─ áudio  → transcribe() [OpenAI API] → texto → ORQUESTRADOR (router decide)
  └─ imagem → REGISTRADOR direto (BinaryContent + instrução)
                                                  ▼
                      SSE stream (igual hoje) de volta ao widget
```

Justificativa do roteamento: uma nota de voz pode ser pergunta **ou** registro —
o router resolve quando é texto. Um recibo fotografado é sempre registro, então
vai direto ao Registrador, evitando o custo extra do router e garantindo que o
`BinaryContent` chegue a quem extrai (o orquestrador delega via string e não
repassaria o binário).

## Componentes

### Backend

**`assistant/services/transcription.py`** (novo)
- `async transcribe_audio(data: bytes, filename: str, content_type: str) -> str`
- Usa o SDK da OpenAI (`audio.transcriptions.create`), modelo por env
  `LLM_TRANSCRIBE_MODEL` (default `gpt-4o-mini-transcribe`), `language="pt"`.
- Cliente OpenAI injetável/mockável (não passa pelo PydanticAI).
- ⚠️ O guard de testes `ALLOW_MODEL_REQUESTS=False` **não** cobre chamadas
  diretas ao SDK da OpenAI → testes **mockam o cliente**.

**`assistant/views.py` — `chat_view`**
- Detecta `Content-Type`:
  - `application/json` → caminho atual (inalterado).
  - `multipart/form-data` → campos: `message` (legenda opcional), `audio`,
    `image` (no máximo um arquivo).
- **Validação** (→ 400 em falha):
  - imagem ≤ `ASSISTANT_MAX_IMAGE_MB` (default 10); content-type em
    {jpeg, png, webp, heic}.
  - áudio ≤ `ASSISTANT_MAX_AUDIO_MB` (default 25 = limite da API); content-type
    em {webm, mp3, mp4/m4a, wav, ogg}.
  - mais de um arquivo, ou nenhum arquivo e sem `message` → 400.
- **Áudio:** `transcribe_audio(...)` → texto; concatena legenda se houver →
  `assistant_agent.run_stream(texto, deps=user, message_history=...)` (caminho
  existente).
- **Imagem:** monta prompt multimodal
  `[instrução, BinaryContent(data=..., media_type=...)]` e roda
  `registrar_agent.run_stream(prompt, deps=user)`. Sem histórico (registro é
  pontual) — confirmar no plano se histórico ajuda.
- Persiste `ChatMessage` do usuário com o **texto** (transcrição/legenda; para
  imagem, algo como "📷 [foto enviada] <legenda>").
- Novo evento SSE **`{"type": "user_text", "content": <texto>}`** emitido antes
  dos tokens, para o widget substituir o balão placeholder pela transcrição.
- Resposta do assistente persistida e `{"type":"done",...}` como hoje.

**`config/settings.py`**
- `LLM_TRANSCRIBE_MODEL` (default `gpt-4o-mini-transcribe`).
- `LLM_VISION_MODEL` (default = `LLM_ORCHESTRATOR_MODEL`) — escape hatch caso o
  modelo leve leia recibo mal; aplicado via override só no run de imagem.
- `ASSISTANT_MAX_IMAGE_MB` (10), `ASSISTANT_MAX_AUDIO_MB` (25).

**`assistant/agents/prompts.py` — `REGISTRAR_PROMPT`**
- Pequeno ajuste: quando a entrada vier de **foto** (recibo), **confirmar um
  resumo dos itens antes de gravar** (recibo com vários itens é mais arriscado);
  aplicar normalmente o colapso por estabelecimento e demais regras-legado.

### Frontend (`frontend/src/cards/ChatWidget.tsx`)

- Botão **🎤**: `MediaRecorder` grava `audio/webm`; estado "gravando" com timer e
  ações parar/cancelar; ao parar, monta `FormData` e envia.
- Botão **📷**: `<input type="file" accept="image/*" capture="environment">`;
  preview-thumbnail opcional; ao selecionar, envia `FormData`.
- Nova `sendMultipart(form: FormData)` que posta em `${apiUrl}chat/` com header
  `X-CSRFToken`, `credentials: same-origin`, e **lê o mesmo stream SSE**
  (incluindo o novo evento `user_text`).
- Balão do usuário mostra "🎤 …" / "📷 …" como placeholder e é atualizado com a
  transcrição/legenda quando `user_text` chega.
- Desabilita controles enquanto `isStreaming`.

## Segurança

- Mesma autenticação + CSRF via header de hoje; todas as queries user-scoped.
- Limites rígidos de tamanho/tipo (anti-abuso e controle de custo de API).
- Entrada de imagem é **não-confiável** (prompt-injection via texto na foto):
  o Registrador trata o conteúdo da imagem como dados a confirmar, nunca como
  instruções; mantém privilégio mínimo (sem ferramentas de leitura analítica) e
  a política de confirmação reforçada para foto.

## Mobile / PWA (Android)

O "app mobile" é o **PWA instalado** (Sprint 10) e o futuro **TWA/Play Store**
(Sprint 11, adiado). É o **mesmo código** — não há build mobile separado; a ilha
React `ChatWidget` e os botões 🎤/📷 aparecem automaticamente no app instalado.

- **📷 Foto:** `accept="image/*" capture="environment"` abre a câmera traseira no
  Android (ou galeria). Funciona em PWA standalone.
- **🎤 Áudio:** `getUserMedia` + `MediaRecorder` exigem contexto seguro (HTTPS —
  Cloud Run ✅) e permissão de microfone (prompt na 1ª vez). Funciona no Chrome
  Android / PWA instalado.
- **Formato por plataforma:** Android Chrome grava `audio/webm;opus`; iOS Safari
  grava `audio/mp4`. Usar `MediaRecorder.isTypeSupported()` para escolher; o
  backend aceita ambos (daí a lista de content-types permitidos).
- **Service worker:** o endpoint é `/api/assistant/chat/` (POST). O SW
  (`templates/sw.js`) já ignora **POST** (`req.method !== 'GET'`) **e** o prefixo
  `/api/` — o upload multipart não é cacheado nem interceptado. Confirmado.
- **Layout:** o widget é `fixed bottom-right w-96 max-w-[calc(100vw-2rem)]`; os
  botões novos devem caber sem overflow em telas estreitas (ver known issue do
  FAB cortado no mobile estreito). Alvos de toque ≥44px.
- **iOS (secundário):** PWA standalone no iOS restringe `getUserMedia`
  historicamente; alvo é Android. Degradação graciosa: esconder 🎤 quando
  `MediaRecorder`/`getUserMedia` não existir.

### Pendências para o TWA (Sprint 11, fora deste ciclo)

Registrado aqui para não esquecer ao empacotar:
- `AndroidManifest.xml` do TWA precisa declarar `RECORD_AUDIO` e `CAMERA`.
- Formulário **Data Safety** da Play Store deve declarar que áudio/foto são
  **enviados a terceiro (OpenAI)** e **não armazenados** ("processar e
  descartar" = não-retenção, mas há **trânsito** dos dados a terceiro).

## Tratamento de erros

- Falha de transcrição (timeout/erro da API) → evento SSE `error` com mensagem
  amigável em pt-BR; nada é gravado.
- Arquivo inválido → 400 antes de qualquer chamada de modelo.
- MediaRecorder indisponível/permissão negada no browser → o widget esconde 🎤
  e mostra aviso (degradação graciosa).

## Testes (TDD; pgvector em :5433)

- **`assistant/tests/test_transcription.py`** — chama o cliente correto com o
  modelo/idioma esperados; retorna texto; propaga/trata erro. Cliente mockado.
- **`assistant/tests/test_views.py`** (estende) —
  - multipart com áudio (transcrição mockada) → emite `user_text` + tokens.
  - multipart com imagem → `registrar_agent` é invocado com `BinaryContent`
    (via `agents_override(TestModel())`).
  - validações de tamanho/tipo → 400; mais de um arquivo → 400.
  - não autenticado → 403.
  - **regressão**: caminho JSON-only inalterado.
- **Frontend:** o repositório **não possui runner de testes JS**. Verificação
  via `npm run build` (typecheck) + QA manual/Playwright no PWA (gravar voz,
  enviar foto pela câmera). Registrado aqui honestamente — sem teste automatizado
  de JS neste ciclo.

## Plano de entrega (etapas; detalhar no plano)

1. Service de transcrição + testes.
2. Settings (envs novas).
3. Endpoint multipart + roteamento + validação + evento `user_text` + testes
   (inclui regressão JSON).
4. Ajuste do `REGISTRAR_PROMPT` (confirmação p/ foto) + testes de prompt.
5. ChatWidget (botões, MediaRecorder, sendMultipart, render `user_text`) + build.
6. Verificação: suíte completa verde, ruff limpo, QA manual PWA.

Tudo em **worktree**; merge na **main local** só após tudo verde (sem remote git).

## Fora de escopo (YAGNI)

Storage/anexo de comprovante; histórico visual de mídia; Whisper local;
múltiplos arquivos por mensagem; transcrição no navegador; OCR dedicado.
