import { useEffect, useRef, useState } from "react";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

interface Props {
  apiUrl: string;
}

const GENERIC_ERROR = "Erro de conexão. Tente novamente.";

/** Lê a mensagem de erro do corpo JSON ({error}) de uma resposta não-OK. */
async function serverError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (data && typeof data.error === "string" && data.error) return data.error;
  } catch {
    // corpo não-JSON (ex.: queda de rede) → mensagem genérica
  }
  return GENERIC_ERROR;
}

/** Texto a exibir a partir de um erro capturado (mensagem do servidor ou genérica). */
function errorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message : GENERIC_ERROR;
}

export default function ChatWidget({ apiUrl }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [recSeconds, setRecSeconds] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recTimerRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const canRecord =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof window !== "undefined" &&
    "MediaRecorder" in window;

  // Load history on first open
  useEffect(() => {
    if (isOpen && messages.length === 0) {
      fetch(`${apiUrl}history/`, { credentials: "same-origin" })
        .then((r) => r.json())
        .then((data: Message[]) => setMessages(data))
        .catch(() => {});
    }
  }, [isOpen, apiUrl]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async (overrideMessage?: string) => {
    const text = overrideMessage ?? input;
    if (!text.trim() || isStreaming) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    // Add placeholder for assistant response
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "" },
    ]);

    try {
      const response = await fetch(`${apiUrl}chat/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken(),
        },
        credentials: "same-origin",
        body: JSON.stringify({ message: userMsg.content }),
      });

      if (!response.ok || !response.body) throw new Error(await serverError(response));

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line);
            if (event.type === "token") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + event.content }
                    : m,
                ),
              );
            } else if (event.type === "error") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: `Erro: ${event.content}` }
                    : m,
                ),
              );
            }
          } catch {
            // Skip unparseable lines
          }
        }
      }
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

  const streamFromResponse = async (
    response: Response,
    assistantId: string,
    userPlaceholderId: string,
  ) => {
    if (!response.ok || !response.body) throw new Error(await serverError(response));
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          if (event.type === "user_text") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === userPlaceholderId
                  ? { ...m, content: event.content }
                  : m,
              ),
            );
          } else if (event.type === "token") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + event.content }
                  : m,
              ),
            );
          } else if (event.type === "error") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: `Erro: ${event.content}` }
                  : m,
              ),
            );
          }
        } catch {
          // skip
        }
      }
    }
  };

  const sendMultipart = async (form: FormData, placeholderLabel: string) => {
    if (isStreaming) return;
    const userId = crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: placeholderLabel },
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

  const handleImagePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("image", file);
    sendMultipart(form, "📷 foto enviada…");
    e.target.value = "";
  };

  const startRecording = async () => {
    if (!canRecord || isStreaming) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "";
      const rec = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        if (recTimerRef.current) window.clearInterval(recTimerRef.current);
        setRecSeconds(0);
        const blob = new Blob(chunksRef.current, {
          type: rec.mimeType || "audio/webm",
        });
        if (blob.size === 0) return;
        const form = new FormData();
        form.append("audio", blob, "nota.webm");
        sendMultipart(form, "🎤 nota de voz…");
      };
      mediaRecorderRef.current = rec;
      rec.start();
      setIsRecording(true);
      setRecSeconds(0);
      recTimerRef.current = window.setInterval(
        () => setRecSeconds((s) => s + 1),
        1000,
      );
    } catch {
      setIsRecording(false);
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  const cancelRecording = () => {
    const rec = mediaRecorderRef.current;
    if (rec) {
      rec.onstop = null;
      rec.stop();
      rec.stream.getTracks().forEach((t) => t.stop());
    }
    if (recTimerRef.current) window.clearInterval(recTimerRef.current);
    setIsRecording(false);
    setRecSeconds(0);
    chunksRef.current = [];
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleClose = () => {
    setIsOpen(false);
    setIsMinimized(false);
  };

  // --- Collapsed state: floating button ---
  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 md:w-16 md:h-16 bg-neutral text-neutral-content rounded-full flex items-center justify-center text-2xl shadow-lg hover:scale-110 transition-transform cursor-pointer"
        title="Abrir assistente"
      >
        🤖
      </button>
    );
  }

  // --- Chat content ---
  const chatHeader = (
    <div className="flex items-center justify-between p-3 bg-neutral text-neutral-content shrink-0">
      <span className="font-bold text-sm">🤖 Assistente</span>
      <div className="flex gap-1">
        <button
          onClick={() => setIsMinimized(!isMinimized)}
          className="btn btn-ghost btn-xs text-neutral-content"
          title={isMinimized ? "Expandir" : "Minimizar"}
        >
          {isMinimized ? "▲" : "▼"}
        </button>
        <button
          onClick={handleClose}
          className="btn btn-ghost btn-xs text-neutral-content"
          title="Fechar"
        >
          ✕
        </button>
      </div>
    </div>
  );

  const chatMessages = (
    <div className="flex-1 overflow-y-auto p-3 space-y-2">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`chat ${msg.role === "user" ? "chat-end" : "chat-start"}`}
        >
          <div
            className={`chat-bubble text-sm ${
              msg.role === "user"
                ? "chat-bubble-primary"
                : "chat-bubble-neutral"
            }`}
          >
            {msg.content || (
              <span className="loading loading-dots loading-sm" />
            )}
          </div>
        </div>
      ))}
      <div ref={messagesEndRef} />
    </div>
  );

  const quickReplies = messages.length > 0 &&
    messages[messages.length - 1].role === "assistant" &&
    messages[messages.length - 1].content.includes("Confirma?") && (
      <div className="flex gap-1 px-3 pb-1">
        <button
          className="btn btn-xs btn-success"
          onClick={() => sendMessage("sim")}
          disabled={isStreaming}
        >
          Sim
        </button>
        <button
          className="btn btn-xs btn-error"
          onClick={() => sendMessage("não")}
          disabled={isStreaming}
        >
          Não
        </button>
      </div>
    );

  const chatInput = (
    <div className="p-3 border-t border-base-300 shrink-0">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={handleImagePick}
      />
      {isRecording ? (
        <div className="flex items-center gap-2">
          <span className="flex-1 text-sm text-error flex items-center gap-2">
            <span className="loading loading-ring loading-sm" />
            Gravando… {recSeconds}s
          </span>
          <button
            onClick={cancelRecording}
            className="btn btn-sm btn-ghost"
            title="Cancelar"
          >
            ✕
          </button>
          <button
            onClick={stopRecording}
            className="btn btn-sm btn-success"
            title="Enviar áudio"
          >
            ⏹
          </button>
        </div>
      ) : (
        <div className="flex gap-1 items-center">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="btn btn-sm btn-ghost btn-square"
            disabled={isStreaming}
            title="Enviar foto"
          >
            📷
          </button>
          {canRecord && (
            <button
              onClick={startRecording}
              className="btn btn-sm btn-ghost btn-square"
              disabled={isStreaming}
              title="Gravar áudio"
            >
              🎤
            </button>
          )}
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Digite sua mensagem..."
            className="input input-bordered input-sm flex-1 min-w-0"
            disabled={isStreaming}
          />
          <button
            onClick={() => sendMessage()}
            className="btn btn-sm btn-accent btn-square"
            disabled={isStreaming || !input.trim()}
          >
            →
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 max-w-[calc(100vw-2rem)] h-[32rem] max-h-[calc(100vh-6rem)] flex flex-col bg-base-100 border border-base-300 rounded-lg shadow-xl">
      {chatHeader}
      {!isMinimized && (
        <>
          {chatMessages}
          {quickReplies}
          {chatInput}
        </>
      )}
    </div>
  );
}

function getCsrfToken(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}
