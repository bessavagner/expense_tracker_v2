# Chat Image Staging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user attach several photos (pages/angles of the *same* receipt) to a chat message, preview them as removable thumbnails, add a guiding caption, and send them together — instead of the current send-on-pick of a single image.

**Architecture:** Frontend stages picked files in React state and renders a thumbnail strip; on send it posts multipart with the `image` field repeated once per photo plus a `message` caption. The backend reads `request.FILES.getlist("image")`, preprocesses each photo, and feeds *all* of them to a single vision extraction (one combined `ReceiptExtraction` → one confirmation). Caption guides the read.

**Tech Stack:** Django 6 async views, PydanticAI (vision via `LLM_VISION_MODEL`), React 18 island + daisyUI/Tailwind, pytest (backend). Frontend has no unit-test runner — verified via `pnpm build` (tsc typecheck + bundle) and manual browser check.

## Global Constraints

- Each photo validated against `ASSISTANT_MAX_IMAGE_MB` (default 10) and `ASSISTANT_ALLOWED_IMAGE_TYPES`. Copy these names verbatim from `config/settings.py`.
- New setting `ASSISTANT_MAX_IMAGES` default **5**, env-overridable.
- Several images = pages/angles of ONE receipt → ONE extraction → ONE confirmation. No batch-of-different-receipts, no general (non-receipt) vision.
- Image bytes are NOT persisted to server history (thumbnails live only in the browser session).
- TDD on backend (pytest exists). Frontend: typecheck/build + manual verification (no FE test runner — do not add one).
- After any frontend change, rebuild `mount.js` + `tailwind.css` and commit them (git-tracked build artifacts; Tailwind needs `--force` for new classes).
- Run backend tests against the pgvector container on port 5433 (project DB convention).
- Branch already created: `feat/chat-image-staging`. Design doc: `docs/.ai/prompts/007_CHAT_IMAGE_STAGING/007_DESIGN_chat_image_staging.md`.

---

## File Structure

- Modify `src/backend/config/settings.py` — add `ASSISTANT_MAX_IMAGES`.
- Modify `src/backend/assistant/agents/extraction.py` — `extract_receipt` takes a list of images; instruction note about same-receipt pages.
- Modify `src/backend/assistant/views.py` — `_handle_multipart` uses `getlist`; `_handle_image` → `_handle_images` (multi-image validate/preprocess/extract/fallback).
- Modify `src/backend/assistant/tests/test_views.py` — new multi-image tests; existing single-image tests stay green.
- Modify `src/backend/frontend/src/cards/ChatWidget.tsx` — staging state, thumbnail strip, multi-image send, bubble thumbnails.
- Modify built artifacts under `src/backend/frontend/` output dir (`mount.js`, `tailwind.css`) — committed after rebuild.

---

## Task 1: `extract_receipt` accepts multiple images (same receipt)

**Files:**
- Modify: `src/backend/assistant/agents/extraction.py`
- Test: `src/backend/assistant/tests/test_extraction.py` (create if absent; otherwise add to the existing extraction test module)

**Interfaces:**
- Consumes: `BinaryContent`, `extraction_agent` (existing).
- Produces: `async def extract_receipt(images: list[tuple[bytes, str]]) -> ReceiptExtraction` — `images` is a list of `(data, media_type)`; all are pages/angles of one receipt.

- [ ] **Step 1: Locate any direct callers of the old signature**

Run: `grep -rn "extract_receipt(" src/backend --include=*.py`
Expected: callers in `assistant/views.py` and possibly a test. Note them — they get updated in this task (the test) and Task 2 (views).

- [ ] **Step 2: Write the failing test**

Create/append `src/backend/assistant/tests/test_extraction.py`:

```python
import pytest
from pydantic_ai import BinaryContent
from pydantic_ai.models.test import TestModel

from assistant.agents.extraction import extract_receipt, extraction_agent


@pytest.mark.asyncio
async def test_extract_receipt_sends_all_images_in_one_run(monkeypatch):
    """Várias imagens (páginas do mesmo recibo) vão num único run de visão."""
    captured = {}

    real_run = extraction_agent.run

    async def spy_run(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return await real_run(prompt, *args, **kwargs)

    monkeypatch.setattr(extraction_agent, "run", spy_run)

    images = [(b"img-a", "image/jpeg"), (b"img-b", "image/png")]
    with extraction_agent.override(model=TestModel()):
        await extract_receipt(images)

    prompt = captured["prompt"]
    binaries = [p for p in prompt if isinstance(p, BinaryContent)]
    assert len(binaries) == 2
    assert binaries[0].data == b"img-a"
    assert binaries[1].media_type == "image/png"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd src/backend && python -m pytest assistant/tests/test_extraction.py::test_extract_receipt_sends_all_images_in_one_run -v`
Expected: FAIL — `extract_receipt` currently takes `(data, media_type)`, so passing a list raises `TypeError`.

- [ ] **Step 4: Implement the new signature**

In `src/backend/assistant/agents/extraction.py`, replace the `extract_receipt` function:

```python
async def extract_receipt(images: list[tuple[bytes, str]]) -> ReceiptExtraction:
    """Lê as fotos do recibo e devolve a extração estruturada.

    ``images`` é uma lista de ``(data, media_type)``. Quando há mais de uma, são
    páginas/ângulos do MESMO recibo e vão juntas num único run de visão.
    """
    prompt = [EXTRACTION_INSTRUCTION]
    prompt += [BinaryContent(data=data, media_type=mt) for data, mt in images]
    result = await extraction_agent.run(prompt)
    return result.output
```

Append to `EXTRACTION_INSTRUCTION` (inside the existing string) a final sentence:

```
"Quando houver MAIS DE UMA imagem, elas são páginas/ângulos do MESMO recibo: "
"combine-as numa única leitura, sem duplicar itens."
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd src/backend && python -m pytest assistant/tests/test_extraction.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backend/assistant/agents/extraction.py src/backend/assistant/tests/test_extraction.py
git commit -m "feat(assistant): extract_receipt accepts multiple images of one receipt"
```

---

## Task 2: Backend handles a list of images (`_handle_images`) + max-count setting

**Files:**
- Modify: `src/backend/config/settings.py` (add `ASSISTANT_MAX_IMAGES`)
- Modify: `src/backend/assistant/views.py`
- Test: `src/backend/assistant/tests/test_views.py`

**Interfaces:**
- Consumes: `extract_receipt(images)` from Task 1; `prepare_receipt_image(data, media_type) -> tuple[bytes, str]`; `settings.ASSISTANT_MAX_IMAGES`.
- Produces: `async def _handle_images(request, user, images, caption)` — `images` is the `getlist("image")` list of `UploadedFile`. Replaces `_handle_image`.

- [ ] **Step 1: Add the setting**

In `src/backend/config/settings.py`, right after `ASSISTANT_MAX_IMAGE_MB`:

```python
ASSISTANT_MAX_IMAGES = int(os.environ.get("ASSISTANT_MAX_IMAGES", "5"))
```

- [ ] **Step 2: Write the failing tests**

Append to `src/backend/assistant/tests/test_views.py` inside `class TestChatEndpoint`:

```python
    _PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
        b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def test_multiple_images_one_extraction(self, logged_client, user, monkeypatch):
        """N fotos => UMA chamada a extract_receipt com N imagens (mesmo recibo)."""
        from assistant.agents.extraction import ReceiptExtraction
        from assistant.agents.registrar import registrar_agent

        captured = {}

        async def fake_extract(images):
            captured["images"] = images
            return ReceiptExtraction()

        monkeypatch.setattr("assistant.views.extract_receipt", fake_extract)

        img1 = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        img2 = SimpleUploadedFile("b.png", self._PNG, content_type="image/png")
        with registrar_agent.override(model=TestModel()):
            response = logged_client.post(
                "/api/assistant/chat/",
                data={"image": [img1, img2], "message": "isso é mercado"},
            )
            consume_streaming(response)

        assert response.status_code == 200
        assert len(captured["images"]) == 2
        # legenda vira rótulo do usuário com contagem de fotos
        assert ChatMessage.objects.filter(
            user=user, role="user", content__icontains="2 fotos"
        ).exists()

    def test_rejects_too_many_images(self, logged_client, user, settings):
        settings.ASSISTANT_MAX_IMAGES = 1
        img1 = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        img2 = SimpleUploadedFile("b.png", self._PNG, content_type="image/png")
        response = logged_client.post(
            "/api/assistant/chat/", data={"image": [img1, img2]}
        )
        assert response.status_code == 400

    def test_rejects_bad_type_among_images(self, logged_client, user):
        good = SimpleUploadedFile("a.png", self._PNG, content_type="image/png")
        bad = SimpleUploadedFile("x.txt", b"\x00", content_type="text/plain")
        response = logged_client.post(
            "/api/assistant/chat/", data={"image": [good, bad]}
        )
        assert response.status_code == 400
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `cd src/backend && python -m pytest assistant/tests/test_views.py -k "multiple_images_one_extraction or too_many_images or bad_type_among_images" -v`
Expected: FAIL — `getlist`/`_handle_images`/`ASSISTANT_MAX_IMAGES` not wired; `extract_receipt` is called with a single image in the old code path.

- [ ] **Step 4: Rewrite `_handle_multipart` to use `getlist`**

In `src/backend/assistant/views.py`, replace the body of `_handle_multipart`:

```python
async def _handle_multipart(request, user):
    caption = (request.POST.get("message") or "").strip()
    images = request.FILES.getlist("image")
    audio = request.FILES.get("audio")

    if images and audio:
        return JsonResponse(
            {"error": "Envie apenas um tipo de arquivo por mensagem."}, status=400
        )
    if not images and not audio and not caption:
        return JsonResponse({"error": "Nada para processar."}, status=400)

    if images:
        return await _handle_images(request, user, images, caption)
    if audio:
        return await _handle_audio(request, user, audio, caption)

    # multipart só com texto: trata como mensagem normal
    await ChatMessage.objects.acreate(
        user=user, role=MessageRole.USER, content=caption
    )
    history = await _load_history(user)
    return _sse_response(user, assistant_agent, caption, message_history=history)
```

- [ ] **Step 5: Replace `_handle_image` with `_handle_images`**

Replace the entire `_handle_image` function with:

```python
async def _handle_images(request, user, images, caption):
    from pydantic_ai import BinaryContent

    if len(images) > settings.ASSISTANT_MAX_IMAGES:
        return JsonResponse(
            {"error": f"Envie no máximo {settings.ASSISTANT_MAX_IMAGES} imagens."},
            status=400,
        )

    max_bytes = settings.ASSISTANT_MAX_IMAGE_MB * 1024 * 1024
    prepared: list[tuple[bytes, str]] = []
    for image in images:
        if image.size > max_bytes:
            return JsonResponse({"error": "Imagem muito grande."}, status=400)
        if image.content_type not in settings.ASSISTANT_ALLOWED_IMAGE_TYPES:
            return JsonResponse(
                {"error": "Formato de imagem não suportado."}, status=400
            )
        data, media_type = prepare_receipt_image(image.read(), image.content_type)
        prepared.append((data, media_type))

    n = len(prepared)
    noun = "foto" if n == 1 else f"{n} fotos"
    if caption:
        user_label = f"📷 [{noun}] {caption}"
    else:
        user_label = "📷 [foto enviada]" if n == 1 else f"📷 [{noun} enviadas]"
    chat_msg = await ChatMessage.objects.acreate(
        user=user, role=MessageRole.USER, content=user_label
    )

    # Fase 1: extração estruturada (combina todas as imagens num recibo).
    extraction = None
    try:
        extraction = await extract_receipt(prepared)
    except Exception:
        logger.exception(
            "Falha na extração estruturada do recibo; fallback para leitura direta."
        )

    if extraction is not None:
        await ReceiptDraft.objects.acreate(
            user=user,
            chat_message=chat_msg,
            payload=extraction.model_dump(mode="json"),
        )
        needs_review = receipt_needs_review(
            extraction, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE
        )
        prompt = extraction_to_prompt(extraction, caption, needs_review=needs_review)
        return _sse_response(
            user,
            registrar_agent,
            prompt,
            message_history=None,
            user_text=user_label,
        )

    # Fallback: manda TODAS as fotos ao registrador com o modelo de visão.
    instruction = (
        "Estas são fotos de um recibo/cupom (páginas/ângulos do mesmo recibo). "
        "Extraia os lançamentos seguindo as regras e confirme um resumo antes de gravar."
    )
    if caption:
        instruction += f" Observação do usuário: {caption}"
    prompt = [instruction]
    prompt += [BinaryContent(data=d, media_type=m) for d, m in prepared]
    return _sse_response(
        user,
        registrar_agent,
        prompt,
        message_history=None,
        user_text=user_label,
        model=settings.LLM_VISION_MODEL,
    )
```

- [ ] **Step 6: Run the full views test module**

Run: `cd src/backend && python -m pytest assistant/tests/test_views.py -v`
Expected: PASS — including pre-existing single-image tests (`test_multipart_image_routes_to_registrar`, `test_image_creates_receipt_draft`, `test_multipart_rejects_oversized_image`, `test_image_uses_vision_model_setting`, `test_image_is_preprocessed_before_send`). The fallback still puts the first `BinaryContent` at `prompt[1]`, so `test_image_is_preprocessed_before_send` stays green.

- [ ] **Step 7: Run the assistant suite to catch regressions**

Run: `cd src/backend && python -m pytest assistant/ -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/backend/config/settings.py src/backend/assistant/views.py src/backend/assistant/tests/test_views.py
git commit -m "feat(assistant): accept multiple receipt photos in one chat message"
```

---

## Task 3: Frontend staging — accumulate picked images, thumbnail strip, remove

**Files:**
- Modify: `src/backend/frontend/src/cards/ChatWidget.tsx`

**Interfaces:**
- Produces: state `attachments: Attachment[]` where `type Attachment = { id: string; file: File; url: string }`; helpers `addFiles(files: FileList | File[])`, `removeAttachment(id: string)`, `clearAttachments()`.

- [ ] **Step 1: Add the Attachment type and state**

Near the top of the component (after the existing `useState` hooks for `attachMenuOpen`), add:

```tsx
interface Attachment {
  id: string;
  file: File;
  url: string;
}

const MAX_IMAGES = 5;
```

Inside `ChatWidget`, add state:

```tsx
const [attachments, setAttachments] = useState<Attachment[]>([]);
```

- [ ] **Step 2: Add add/remove/clear helpers**

```tsx
const addFiles = (files: FileList | File[]) => {
  const picked = Array.from(files).filter((f) => f.type.startsWith("image/"));
  if (picked.length === 0) return;
  setAttachments((prev) => {
    const room = MAX_IMAGES - prev.length;
    const next = picked.slice(0, Math.max(0, room)).map((file) => ({
      id: randomId(),
      file,
      url: URL.createObjectURL(file),
    }));
    return [...prev, ...next];
  });
};

const removeAttachment = (id: string) => {
  setAttachments((prev) => {
    const found = prev.find((a) => a.id === id);
    if (found) URL.revokeObjectURL(found.url);
    return prev.filter((a) => a.id !== id);
  });
};

const clearAttachments = () => {
  setAttachments((prev) => {
    prev.forEach((a) => URL.revokeObjectURL(a.url));
    return [];
  });
};
```

- [ ] **Step 3: Make `handleImagePick` accumulate instead of send**

Replace `handleImagePick`:

```tsx
const handleImagePick = (e: React.ChangeEvent<HTMLInputElement>) => {
  if (e.target.files) addFiles(e.target.files);
  e.target.value = "";
};
```

- [ ] **Step 4: Allow multiple selection on the file (gallery) input**

In the gallery `<input>` (the one with `ref={fileInputRef}`), add the `multiple` attribute:

```tsx
<input
  ref={fileInputRef}
  type="file"
  accept="image/*"
  multiple
  className="hidden"
  onChange={handleImagePick}
/>
```

Leave the camera input single (no `multiple`) — capture is one shot.

- [ ] **Step 5: Render the thumbnail strip above the input row**

Inside `chatInput`, immediately before the `isRecording ? (...) : (...)` ternary, add:

```tsx
{attachments.length > 0 && (
  <div className="flex flex-wrap gap-2 mb-2">
    {attachments.map((a) => (
      <div key={a.id} className="relative w-14 h-14">
        <img
          src={a.url}
          alt="anexo"
          className="w-14 h-14 object-cover rounded border border-base-300"
        />
        <button
          type="button"
          onClick={() => removeAttachment(a.id)}
          className="absolute -top-1.5 -right-1.5 btn btn-xs btn-circle btn-error"
          title="Remover"
          aria-label="Remover imagem"
        >
          ✕
        </button>
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 6: Revoke object URLs on unmount**

Add an effect (near the other effects):

```tsx
useEffect(() => {
  return () => {
    attachments.forEach((a) => URL.revokeObjectURL(a.url));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []);
```

- [ ] **Step 7: Typecheck**

Run: `cd src/backend/frontend && pnpm build`
Expected: `tsc` passes (no type errors), vite bundle written. (`attachments` is currently set but not yet consumed by send — that's Task 4. If `tsc` flags it as unused, leave it; it's referenced by the strip render and helpers, so it should be fine.)

- [ ] **Step 8: Commit (source only; artifacts rebuilt in Task 5)**

```bash
git add src/backend/frontend/src/cards/ChatWidget.tsx
git commit -m "feat(chat): stage picked images as removable thumbnails"
```

---

## Task 4: Frontend send — post all staged images + caption together

**Files:**
- Modify: `src/backend/frontend/src/cards/ChatWidget.tsx`

**Interfaces:**
- Consumes: `attachments` state, `clearAttachments`, existing `sendMultipart(form, placeholderLabel)`, existing `sendMessage`.
- Produces: updated `sendMessage` that branches to multipart when attachments exist; `Message.images?: string[]` for in-session bubble thumbnails.

- [ ] **Step 1: Extend the Message interface with optional images**

At the top `interface Message`, add:

```tsx
interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  images?: string[];
}
```

- [ ] **Step 2: Let `sendMultipart` carry preview URLs into the user bubble**

Change `sendMultipart` signature and the user placeholder it inserts:

```tsx
const sendMultipart = async (
  form: FormData,
  placeholderLabel: string,
  previewUrls: string[] = [],
) => {
  if (isStreaming) return;
  const userId = randomId();
  const assistantId = randomId();
  setMessages((prev) => [
    ...prev,
    { id: userId, role: "user", content: placeholderLabel, images: previewUrls },
    { id: assistantId, role: "assistant", content: "" },
  ]);
  setIsStreaming(true);
  try {
    const response = await fetch(`${apiUrl}chat/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      credentials: "same-origin",
      body: form,
    });
    await streamFromResponse(response, assistantId, userId);
  } catch (err) {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === assistantId ? { ...m, content: errorText(err) } : m,
      ),
    );
  } finally {
    setIsStreaming(false);
  }
};
```

(The audio caller `sendMultipart(form, "🎤 nota de voz…")` keeps working — `previewUrls` defaults to `[]`.)

- [ ] **Step 3: Branch `sendMessage` to multipart when attachments exist**

At the very start of `sendMessage`, before the text-only guard, add:

```tsx
const sendMessage = async (overrideMessage?: string) => {
  if (isStreaming) return;

  // Há imagens encartadas: envia tudo (texto + fotos) como multipart.
  if (attachments.length > 0 && overrideMessage === undefined) {
    const caption = input.trim();
    const form = new FormData();
    attachments.forEach((a) => form.append("image", a.file));
    if (caption) form.append("message", caption);
    const n = attachments.length;
    const label = caption
      ? caption
      : `📷 ${n} ${n === 1 ? "foto" : "fotos"}`;
    const previews = attachments.map((a) => a.url);
    setInput("");
    clearAttachments();
    await sendMultipart(form, label, previews);
    return;
  }

  const text = overrideMessage ?? input;
  if (!text.trim()) return;
  // ... existing text-only body unchanged ...
```

Keep the rest of the existing `sendMessage` body as-is (the original `if (!text.trim() || isStreaming) return;` line is now replaced by the `isStreaming` guard at top plus `if (!text.trim()) return;`). Do not duplicate the `isStreaming` check.

- [ ] **Step 4: Enable the send button with attachments OR text**

Change the send button's `disabled`:

```tsx
<button
  onClick={() => sendMessage()}
  className="btn btn-sm btn-accent btn-square"
  disabled={isStreaming || (!input.trim() && attachments.length === 0)}
>
  →
</button>
```

- [ ] **Step 5: Render thumbnails inside the user bubble (in-session)**

In `chatMessages`, inside the bubble, render images above the text when present. Replace the bubble inner content block with:

```tsx
<div
  className={`chat-bubble text-sm ${
    msg.role === "user" ? "chat-bubble-primary" : "chat-bubble-neutral"
  }`}
>
  {msg.images && msg.images.length > 0 && (
    <div className="flex flex-wrap gap-1 mb-1">
      {msg.images.map((src, i) => (
        <img
          key={i}
          src={src}
          alt="anexo"
          className="w-16 h-16 object-cover rounded"
        />
      ))}
    </div>
  )}
  {msg.content ? (
    msg.role === "assistant" ? (
      <MarkdownMessage content={msg.content} />
    ) : (
      <span className="whitespace-pre-wrap">{msg.content}</span>
    )
  ) : (
    <span className="loading loading-dots loading-sm" />
  )}
</div>
```

- [ ] **Step 6: Disable the attach (paperclip) button while at the image limit**

In the paperclip button, extend `disabled`:

```tsx
disabled={isStreaming || attachments.length >= MAX_IMAGES}
```

- [ ] **Step 7: Typecheck/build**

Run: `cd src/backend/frontend && pnpm build`
Expected: PASS (no type errors). Confirm there are no unused-variable errors for `clearAttachments`/`attachments`.

- [ ] **Step 8: Commit (source only)**

```bash
git add src/backend/frontend/src/cards/ChatWidget.tsx
git commit -m "feat(chat): send staged images with caption in one multipart message"
```

---

## Task 5: Rebuild frontend artifacts + manual verification

**Files:**
- Modify (generated): `mount.js`, `tailwind.css` under the frontend build output dir.

- [ ] **Step 1: Rebuild artifacts (Tailwind needs --force for new classes)**

Run the project's frontend build. Confirm the exact command/output path from `vite.config.ts` and existing build scripts; per memory, Tailwind must be rebuilt with `--force` so new utility classes aren't stale:

Run: `cd src/backend/frontend && pnpm build`
Then rebuild Tailwind CSS with `--force` per the project's documented procedure (see memory *Frontend build artifacts*).
Expected: updated `mount.js` and `tailwind.css`.

- [ ] **Step 2: Manual verification in the browser**

Start the app (per project run skill / dev services) and verify:
1. Paperclip → Arquivo allows selecting **multiple** images; thumbnails appear above the input.
2. Each thumbnail has a working ✕ remove; removing frees it from the strip.
3. Camera adds one photo to the strip (does not auto-send).
4. Typing a caption + pressing Enter/→ sends once; the user bubble shows the thumbnails + caption; the assistant replies with a single receipt confirmation.
5. Selecting a 6th image is blocked (paperclip disabled at 5).
6. Sending with NO attachments still works as plain text (regression).
7. Audio recording still works (regression).

- [ ] **Step 3: Commit artifacts**

```bash
git add src/backend/frontend  # includes rebuilt mount.js + tailwind.css
git commit -m "build(chat): rebuild frontend artifacts for image staging"
```

---

## Task 6: Full regression sweep

- [ ] **Step 1: Backend tests**

Run: `cd src/backend && python -m pytest assistant/ -q`
Expected: PASS (DB on port 5433).

- [ ] **Step 2: Frontend build clean**

Run: `cd src/backend/frontend && pnpm build`
Expected: PASS, no type errors.

- [ ] **Step 3: Lint (backend)**

Run: `cd src/backend && ruff check assistant/`
Expected: clean.

---

## Self-Review Notes (coverage map)

- Spec §3 (frontend staging/thumbnails/remove/limit/send/bubble) → Tasks 3, 4, 5.
- Spec §4.1 (`extract_receipt` multi-image + instruction) → Task 1.
- Spec §4.2 (`getlist`, `_handle_images`, count/type/size validation, label, fallback) → Task 2.
- Spec §4.3 (`ASSISTANT_MAX_IMAGES`) → Task 2 Step 1.
- Spec §5 backend tests → Tasks 1, 2; frontend (no runner) → manual verification Task 5.
- Spec §6 rebuild artifacts → Task 5.
