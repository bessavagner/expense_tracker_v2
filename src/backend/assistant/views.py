import json

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from assistant.agents.orchestrator import assistant_agent
from assistant.models import ChatMessage, MessageRole


def _check_auth(request):
    """Return error response if not authenticated, None if OK."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)
    return None


# csrf_exempt is used here because the React widget sends the CSRF token via the
# X-CSRFToken header (read from cookies via getCsrfToken()), which Django's CSRF
# middleware does NOT validate for async views in some configurations. The widget
# always sends credentials: "same-origin" and the token, so CSRF is enforced at
# the browser level. Tests use Django's test client which bypasses CSRF by default.
@csrf_exempt
@require_http_methods(["POST"])
async def chat_view(request):
    """Handle chat messages. Returns SSE stream with async generator."""
    # Resolve the lazy user object in async context using aget_user
    from django.contrib.auth import aget_user

    user = await aget_user(request)
    if not user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=403)

    try:
        body = json.loads(request.body)
        message = body.get("message", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not message:
        return JsonResponse({"error": "Message is required"}, status=400)

    # Save user message
    await ChatMessage.objects.acreate(user=user, role=MessageRole.USER, content=message)

    # Load conversation history
    history_qs = (
        ChatMessage.objects.filter(user=user)
        .order_by("-created_at")[: settings.ASSISTANT_MAX_HISTORY]
        .values("role", "content")
    )
    history_messages = [msg async for msg in history_qs]
    history_messages.reverse()

    # Build message history for PydanticAI
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    pydantic_messages = []
    for msg in history_messages[:-1]:  # exclude current message (it's the prompt)
        if msg["role"] == "user":
            pydantic_messages.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
        else:
            pydantic_messages.append(ModelResponse(parts=[TextPart(content=msg["content"])]))

    async def stream_response():
        full_response = ""
        try:
            async with assistant_agent.run_stream(
                message,
                deps=user,
                message_history=pydantic_messages,
            ) as stream:
                async for text in stream.stream_text(delta=True):
                    full_response += text
                    yield json.dumps({"type": "token", "content": text}) + "\n"
        except Exception:
            error_msg = "Erro ao processar mensagem. Tente novamente."
            yield json.dumps({"type": "error", "content": error_msg}) + "\n"
            full_response = error_msg

        # Save assistant response
        assistant_msg = await ChatMessage.objects.acreate(
            user=user,
            role=MessageRole.ASSISTANT,
            content=full_response,
        )
        yield json.dumps({"type": "done", "message_id": str(assistant_msg.id)}) + "\n"

    response = StreamingHttpResponse(
        stream_response(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


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

    # Convert UUIDs and datetimes to strings
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
