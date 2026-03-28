import { useEffect, useRef, useState, useCallback } from "react";
import { useChatPinned } from "../hooks/useChatPinned";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

interface Props {
  apiUrl: string;
}

export default function ChatWidget({ apiUrl }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const { isPinned, setIsPinned } = useChatPinned();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const resizeRef = useRef<{ startX: number; startWidth: number } | null>(null);

  // Restore pinned state on mount
  useEffect(() => {
    if (isPinned) {
      setIsOpen(true);
      window.dispatchEvent(
        new CustomEvent("chat:pin", { detail: { width: 380 } }),
      );
    }
  }, []);

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

      if (!response.ok || !response.body) throw new Error("Request failed");

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
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: "Erro de conexão. Tente novamente." }
            : m,
        ),
      );
    } finally {
      setIsStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // Resize handlers for pinned mode
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const aside = (e.target as HTMLElement).closest("aside");
    const startWidth = aside?.getBoundingClientRect().width || 380;
    resizeRef.current = { startX: e.clientX, startWidth };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      const delta = resizeRef.current.startX - e.clientX;
      const newWidth = Math.max(
        300,
        Math.min(600, resizeRef.current.startWidth + delta),
      );
      window.dispatchEvent(
        new CustomEvent("chat:resize", { detail: { width: newWidth } }),
      );
    };

    const handleMouseUp = () => {
      resizeRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, []);

  const handlePin = () => {
    if (isPinned) {
      setIsPinned(false);
    } else {
      setIsPinned(true);
      setIsOpen(true);
      setIsMinimized(false);
    }
  };

  const handleClose = () => {
    setIsOpen(false);
    setIsMinimized(false);
    if (isPinned) setIsPinned(false);
  };

  // --- Collapsed state: floating button ---
  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="w-12 h-12 bg-neutral text-neutral-content rounded-full flex items-center justify-center text-xl shadow-lg hover:scale-110 transition-transform cursor-pointer"
        title="Abrir chat"
      >
        💬
      </button>
    );
  }

  // --- Chat content (shared between pinned and floating) ---
  const chatHeader = (
    <div className="flex items-center justify-between p-3 bg-neutral text-neutral-content shrink-0">
      <span className="font-bold text-sm">💬 Assistente</span>
      <div className="flex gap-1">
        <button
          onClick={handlePin}
          className={`btn btn-ghost btn-xs text-neutral-content ${isPinned ? "opacity-100" : "opacity-60"}`}
          title={isPinned ? "Desafixar" : "Fixar"}
        >
          📌
        </button>
        {isPinned && (
          <button
            onClick={() => setIsMinimized(!isMinimized)}
            className="btn btn-ghost btn-xs text-neutral-content"
            title={isMinimized ? "Expandir" : "Minimizar"}
          >
            {isMinimized ? "▲" : "▼"}
          </button>
        )}
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
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Digite sua mensagem..."
          className="input input-bordered input-sm flex-1"
          disabled={isStreaming}
        />
        <button
          onClick={() => sendMessage()}
          className="btn btn-sm btn-accent"
          disabled={isStreaming || !input.trim()}
        >
          →
        </button>
      </div>
    </div>
  );

  // --- Pinned mode ---
  if (isPinned) {
    return (
      <div className="flex h-full">
        {/* Resize handle */}
        <div
          className="w-1 hover:bg-accent/30 cursor-col-resize transition-colors group relative shrink-0"
          onMouseDown={handleResizeStart}
        >
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </div>
        <div className="flex flex-col flex-1 bg-base-100 min-w-0">
          {chatHeader}
          {!isMinimized && (
            <>
              {chatMessages}
              {quickReplies}
              {chatInput}
            </>
          )}
        </div>
      </div>
    );
  }

  // --- Floating mode (popup) ---
  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 h-[32rem] flex flex-col bg-base-100 border border-base-300 rounded-lg shadow-xl">
      {chatHeader}
      {chatMessages}
      {quickReplies}
      {chatInput}
    </div>
  );
}

function getCsrfToken(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}
