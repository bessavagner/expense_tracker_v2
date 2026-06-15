import json
import logging

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from assistant.agents.orchestrator import assistant_agent
from assistant.agents.registrar import registrar_agent
from assistant.models import ChatMessage, MessageRole
from assistant.services.image_prep import prepare_receipt_image
from assistant.services.transcription import transcribe_audio

logger = logging.getLogger(__name__)

# Ferramentas que ESCREVEM dados financeiros. Cobrem os dois caminhos: o
# orquestrador delega escrita via ``delegate_registro``; o registrador (usado
# direto no fluxo de imagem) chama as ferramentas concretas. Detectar qualquer
# uma sinaliza ao front que a tela deve recarregar (item #5).
MUTATING_TOOLS = frozenset(
    {
        "delegate_registro",
        "register_entry",
        "add_category",
        "set_category_budget",
        "add_payment_method",
        "set_income",
        "set_systemic_amount",
    }
)


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
            pydantic_messages.append(
                ModelRequest(parts=[UserPromptPart(content=msg["content"])])
            )
        else:
            pydantic_messages.append(
                ModelResponse(parts=[TextPart(content=msg["content"])])
            )
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


async def _handle_json(request, user):
    try:
        body = json.loads(request.body)
        message = body.get("message", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not message:
        return JsonResponse({"error": "Message is required"}, status=400)

    await ChatMessage.objects.acreate(
        user=user, role=MessageRole.USER, content=message
    )
    history = await _load_history(user)
    return _sse_response(user, assistant_agent, message, message_history=history)


async def _handle_multipart(request, user):
    caption = (request.POST.get("message") or "").strip()
    image = request.FILES.get("image")
    audio = request.FILES.get("audio")

    if image and audio:
        return JsonResponse(
            {"error": "Envie apenas um arquivo por mensagem."}, status=400
        )
    if not image and not audio and not caption:
        return JsonResponse({"error": "Nada para processar."}, status=400)

    if image:
        return await _handle_image(request, user, image, caption)
    if audio:
        return await _handle_audio(request, user, audio, caption)

    # multipart só com texto: trata como mensagem normal
    await ChatMessage.objects.acreate(
        user=user, role=MessageRole.USER, content=caption
    )
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
    await ChatMessage.objects.acreate(
        user=user, role=MessageRole.USER, content=message
    )
    history = await _load_history(user)
    return _sse_response(
        user, assistant_agent, message, message_history=history, user_text=message
    )


async def _handle_image(request, user, image, caption):
    from pydantic_ai import BinaryContent

    max_bytes = settings.ASSISTANT_MAX_IMAGE_MB * 1024 * 1024
    if image.size > max_bytes:
        return JsonResponse({"error": "Imagem muito grande."}, status=400)
    if image.content_type not in settings.ASSISTANT_ALLOWED_IMAGE_TYPES:
        return JsonResponse({"error": "Formato de imagem não suportado."}, status=400)

    data = image.read()
    data, media_type = prepare_receipt_image(data, image.content_type)
    instruction = (
        "Esta é a foto de um recibo/cupom. Extraia os lançamentos seguindo as "
        "regras e confirme um resumo antes de gravar."
    )
    if caption:
        instruction += f" Observação do usuário: {caption}"

    user_label = f"📷 [foto] {caption}".strip() if caption else "📷 [foto enviada]"
    await ChatMessage.objects.acreate(
        user=user, role=MessageRole.USER, content=user_label
    )

    prompt = [instruction, BinaryContent(data=data, media_type=media_type)]
    # Registro a partir de foto é pontual: sem histórico de conversa. O recibo é
    # lido com o modelo de visão (LLM_VISION_MODEL), não com o modelo leve.
    return _sse_response(
        user,
        registrar_agent,
        prompt,
        message_history=None,
        user_text=user_label,
        model=settings.LLM_VISION_MODEL,
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
