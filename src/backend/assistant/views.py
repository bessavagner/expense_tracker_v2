import json
import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from assistant.agents.assistant import assistant_agent
from assistant.agents.extraction import (
    extract_receipt,
    extraction_to_prompt,
    receipt_needs_review,
)
from assistant.models import ChatMessage, MessageRole, ReceiptDraft
from assistant.services.image_prep import prepare_receipt_image
from assistant.services.transcription import transcribe_audio

logger = logging.getLogger(__name__)

# Ferramentas que ESCREVEM dados financeiros. Detectar qualquer uma sinaliza ao
# front que a tela deve recarregar (item #5).
MUTATING_TOOLS = frozenset({
    "register_entry", "commit_receipt", "add_category", "set_category_budget",
    "add_payment_method", "set_income", "set_systemic_amount",
    "update_entry", "delete_entry",
})


def _run_mutated_data(messages) -> bool:
    """True se alguma ferramenta de escrita foi chamada nas mensagens do run."""
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if (
                getattr(part, "part_kind", None) == "tool-call"
                and getattr(part, "tool_name", None) in MUTATING_TOOLS
            ):
                return True
    return False


def _check_auth(request):
    """Return error response if not authenticated, None if OK."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)
    return None


async def _load_history(user):
    """Histórico PydanticAI (exclui a última msg, que vira o prompt atual)."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    history_qs = (
        ChatMessage.objects.filter(user=user)
        .order_by("-created_at")[: settings.ASSISTANT_MAX_HISTORY]
        .values("role", "content")
    )
    history_messages = [msg async for msg in history_qs]
    history_messages.reverse()

    pydantic_messages = []
    for msg in history_messages[:-1]:
        if msg["role"] == "user":
            pydantic_messages.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
        else:
            pydantic_messages.append(ModelResponse(parts=[TextPart(content=msg["content"])]))
    return pydantic_messages


def _sse_response(user, agent, prompt, *, message_history, user_text=None, model=None):
    """Monta a StreamingHttpResponse SSE para qualquer agente/prompt.

    Se ``user_text`` for dado, emite um evento ``user_text`` antes dos tokens
    (para o widget substituir o balão placeholder pela transcrição/legenda).

    ``model`` faz override por execução do modelo do agente (usado no fluxo de
    foto para ler o recibo com ``LLM_VISION_MODEL``). Em testes,
    ``agent.override(model=...)`` tem precedência sobre este argumento.
    """

    async def stream_response():
        if user_text:
            yield json.dumps({"type": "user_text", "content": user_text}, ensure_ascii=False) + "\n"

        full_response = ""
        data_changed = False
        try:
            async with agent.run_stream(
                prompt, deps=user, message_history=message_history, model=model
            ) as stream:
                async for text in stream.stream_text(delta=True):
                    full_response += text
                    yield json.dumps({"type": "token", "content": text}, ensure_ascii=False) + "\n"
                try:
                    data_changed = _run_mutated_data(stream.all_messages())
                except Exception:
                    data_changed = False
        except Exception:
            error_msg = "Erro ao processar mensagem. Tente novamente."
            yield json.dumps({"type": "error", "content": error_msg}, ensure_ascii=False) + "\n"
            full_response = error_msg

        assistant_msg = await ChatMessage.objects.acreate(
            user=user,
            role=MessageRole.ASSISTANT,
            content=full_response,
        )
        yield (
            json.dumps(
                {
                    "type": "done",
                    "message_id": str(assistant_msg.id),
                    "data_changed": data_changed,
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    response = StreamingHttpResponse(
        stream_response(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# csrf_exempt: o widget React envia o token CSRF via header X-CSRFToken (lido do
# cookie). credentials: same-origin garante envio do cookie. Testes usam o test
# client do Django, que ignora CSRF.
@csrf_exempt
@require_http_methods(["POST"])
async def chat_view(request):
    """Chat. Aceita JSON (texto) ou multipart/form-data (áudio/imagem)."""
    from django.contrib.auth import aget_user

    user = await aget_user(request)
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    content_type = request.content_type or ""
    if content_type.startswith("multipart/form-data"):
        return await _handle_multipart(request, user)
    return await _handle_json(request, user)


async def _pending_receipt(user):
    from assistant.models import ReceiptDraft, ReceiptDraftStatus

    return await (
        ReceiptDraft.objects.filter(user=user, status=ReceiptDraftStatus.PENDING)
        .order_by("-created_at")
        .afirst()
    )


async def _handle_json(request, user):
    try:
        body = json.loads(request.body)
        message = body.get("message", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not message:
        return JsonResponse({"error": "Message is required"}, status=400)

    await ChatMessage.objects.acreate(user=user, role=MessageRole.USER, content=message)
    if await _pending_receipt(user):
        return _sse_response(user, assistant_agent, message, message_history=None)
    history = await _load_history(user)
    return _sse_response(user, assistant_agent, message, message_history=history)


async def _handle_multipart(request, user):
    caption = (request.POST.get("message") or "").strip()
    images = request.FILES.getlist("image")
    audio = request.FILES.get("audio")

    if images and audio:
        return JsonResponse({"error": "Envie apenas um tipo de arquivo por mensagem."}, status=400)
    if not images and not audio and not caption:
        return JsonResponse({"error": "Nada para processar."}, status=400)

    if images:
        return await _handle_images(request, user, images, caption)
    if audio:
        return await _handle_audio(request, user, audio, caption)

    # multipart só com texto: trata como mensagem normal
    await ChatMessage.objects.acreate(user=user, role=MessageRole.USER, content=caption)
    if await _pending_receipt(user):
        return _sse_response(user, assistant_agent, caption, message_history=None)
    history = await _load_history(user)
    return _sse_response(user, assistant_agent, caption, message_history=history)


async def _handle_audio(request, user, audio, caption):
    max_bytes = settings.ASSISTANT_MAX_AUDIO_MB * 1024 * 1024
    if audio.size > max_bytes:
        return JsonResponse({"error": "Áudio muito grande."}, status=400)
    if audio.content_type not in settings.ASSISTANT_ALLOWED_AUDIO_TYPES:
        return JsonResponse({"error": "Formato de áudio não suportado."}, status=400)

    data = audio.read()
    try:
        text = await transcribe_audio(data, audio.name, audio.content_type)
    except Exception:
        logger.exception(
            "Falha ao transcrever áudio (content_type=%s, %d bytes)",
            audio.content_type,
            len(data),
        )
        return JsonResponse(
            {"error": "Não consegui transcrever o áudio. Tente novamente."},
            status=502,
        )

    message = f"{caption}\n{text}".strip() if caption else text
    await ChatMessage.objects.acreate(user=user, role=MessageRole.USER, content=message)
    if await _pending_receipt(user):
        return _sse_response(
            user, assistant_agent, message, message_history=None, user_text=message
        )
    history = await _load_history(user)
    return _sse_response(user, assistant_agent, message, message_history=history, user_text=message)


async def _handle_images(request, user, images, caption):
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
            return JsonResponse({"error": "Formato de imagem não suportado."}, status=400)
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

    from assistant.agents.tools import (
        discard_pending_receipts,
        list_categories,
        list_payment_methods,
    )

    # Nova foto = novo recibo: abandona qualquer pendente anterior, garantindo no
    # máximo UM draft pendente (evita ressuscitar drafts órfãos num commit
    # posterior — bug real do frete pós-commit que regravou um draft antigo).
    await sync_to_async(discard_pending_receipts)(user)

    cats = await sync_to_async(list_categories)(user)
    pms = await sync_to_async(list_payment_methods)(user)

    # Fase 1: extração estruturada (combina todas as imagens num recibo).
    extraction = None
    try:
        extraction = await extract_receipt(prepared, categories=cats, payment_methods=pms)
    except Exception:
        logger.exception("Falha na extração estruturada do recibo; tentando com modelo de visão.")

    if extraction is not None:
        await ReceiptDraft.objects.acreate(
            user=user,
            chat_message=chat_msg,
            payload=extraction.model_dump(mode="json"),
        )
        needs_review = receipt_needs_review(extraction, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE)
        prompt = extraction_to_prompt(extraction, caption, needs_review=needs_review)
        return _sse_response(
            user,
            assistant_agent,
            prompt,
            message_history=None,
            user_text=user_label,
        )

    # Fallback: tenta UMA vez a extração com o modelo de visão; sem sucesso,
    # pede reenvio (nunca grava direto).
    try:
        extraction = await extract_receipt(
            prepared, categories=cats, payment_methods=pms, model=settings.LLM_VISION_MODEL
        )
    except Exception:
        logger.exception("Extração do recibo falhou mesmo com o modelo de visão.")
        extraction = None

    if extraction is None:

        async def _resend():
            msg = (
                "Não consegui ler esse recibo com segurança. Pode reenviar a foto "
                "(mais nítida / completa) ou me diga os itens por texto?"
            )
            yield (
                json.dumps({"type": "user_text", "content": user_label}, ensure_ascii=False) + "\n"
            )
            yield json.dumps({"type": "token", "content": msg}, ensure_ascii=False) + "\n"
            assistant_msg = await ChatMessage.objects.acreate(
                user=user, role=MessageRole.ASSISTANT, content=msg
            )
            yield (
                json.dumps(
                    {"type": "done", "message_id": str(assistant_msg.id), "data_changed": False},
                    ensure_ascii=False,
                )
                + "\n"
            )

        resp = StreamingHttpResponse(_resend(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp["X-Accel-Buffering"] = "no"
        return resp

    await ReceiptDraft.objects.acreate(
        user=user, chat_message=chat_msg, payload=extraction.model_dump(mode="json")
    )
    needs_review = receipt_needs_review(extraction, settings.ASSISTANT_RECEIPT_MIN_CONFIDENCE)
    prompt = extraction_to_prompt(extraction, caption, needs_review=needs_review)
    return _sse_response(
        user, assistant_agent, prompt, message_history=None, user_text=user_label
    )


@require_GET
def history_view(request):
    """Return chat history for the current user."""
    auth_error = _check_auth(request)
    if auth_error:
        return auth_error

    messages = (
        ChatMessage.objects.filter(user=request.user)
        .order_by("-created_at")[:50]
        .values("id", "role", "content", "created_at")
    )
    messages_list = list(messages)
    messages_list.reverse()

    result = [
        {
            "id": str(m["id"]),
            "role": m["role"],
            "content": m["content"],
            "created_at": m["created_at"].isoformat(),
        }
        for m in messages_list
    ]
    return JsonResponse(result, safe=False)
