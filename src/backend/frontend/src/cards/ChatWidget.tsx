import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
  images?: string[];
}

interface Attachment {
  id: string;
  file: File;
  url: string;
}

const MAX_IMAGES = 5;

interface Props {
  apiUrl: string;
}

const GENERIC_ERROR = "Erro de conexão. Tente novamente.";

// Modo "fixado à direita" com resize mútuo (item #2).
const CHAT_PINNED_KEY = "chat_pinned";
const CHAT_WIDTH_KEY = "chat_width";
// Estado aberto/fechado persistido: páginas sem cards recarregam ao mudar dados
// (ver mount.tsx) e remontariam o chat fechado, "minimizando-o" sozinho.
const CHAT_OPEN_KEY = "chat_open";
const MD_BREAKPOINT = 768; // abaixo disto: sempre flutuante
const MIN_PANEL_PX = 320;
const MAX_PANEL_FRAC = 0.6; // no máximo 60% da largura da janela
const DEFAULT_PANEL_PX = 420;

/** Largura do painel, presa entre o mínimo e 60% da janela. */
function clampPanelWidth(px: number): number {
  const max = Math.max(MIN_PANEL_PX, Math.floor(window.innerWidth * MAX_PANEL_FRAC));
  return Math.min(Math.max(px, MIN_PANEL_PX), max);
}

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

/** Avisa a página que dados financeiros mudaram, para cards/HTMX recarregarem. */
function notifyDataChanged() {
  window.dispatchEvent(new CustomEvent("data-changed"));
}

/** Clipe de papel (anexar). */
const PaperclipIcon = () => (
  <svg
    className="w-5 h-5"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);

/** Microfone (gravar áudio). */
const MicIcon = () => (
  <svg
    className="w-5 h-5"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="22" />
  </svg>
);

/** Câmera (tirar foto). */
const CameraIcon = () => (
  <svg
    className="w-4 h-4"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
    <circle cx="12" cy="13" r="3" />
  </svg>
);

/** Painel à direita (fixar/desfixar o chat na lateral). */
const DockIcon = ({ active }: { active: boolean }) => (
  <svg
    className="w-4 h-4"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <line x1="15" y1="3" x2="15" y2="21" />
    {active && <rect x="15" y="3" width="6" height="18" fill="currentColor" stroke="none" />}
  </svg>
);

/** Documento/arquivo (escolher da galeria). */
const FileIcon = () => (
  <svg
    className="w-4 h-4"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    viewBox="0 0 24 24"
    aria-hidden="true"
  >
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
  </svg>
);

// Overrides para o markdown do chat: tabelas/listas/links com classes daisyUI.
// `node` é descartado para não vazar como atributo do DOM.
const MD_COMPONENTS: Components = {
  table: ({ node: _n, ...props }) => (
    <div className="overflow-x-auto my-1">
      <table className="table table-xs" {...props} />
    </div>
  ),
  th: ({ node: _n, ...props }) => <th className="font-semibold" {...props} />,
  a: ({ node: _n, ...props }) => (
    <a className="link link-primary" target="_blank" rel="noreferrer" {...props} />
  ),
  ul: ({ node: _n, ...props }) => <ul className="list-disc ml-4 my-1" {...props} />,
  ol: ({ node: _n, ...props }) => <ol className="list-decimal ml-4 my-1" {...props} />,
  code: ({ node: _n, ...props }) => (
    <code className="px-1 rounded bg-base-300/60" {...props} />
  ),
  p: ({ node: _n, ...props }) => <p className="my-1 first:mt-0 last:mb-0" {...props} />,
};

/** Renderiza markdown (tabelas GFM, negrito, listas) nas respostas do assistente. */
function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  );
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
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const attachMenuRef = useRef<HTMLDivElement>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const attachmentsRef = useRef<Attachment[]>([]);

  // Pin/resize (item #2)
  const [isPinned, setIsPinned] = useState(false);
  const [panelWidth, setPanelWidth] = useState(DEFAULT_PANEL_PX);
  const [isWide, setIsWide] = useState(true);
  const [isResizing, setIsResizing] = useState(false);
  // Só "encaixa" de fato quando aberto, fixado e em tela larga.
  const docked = isOpen && isPinned && isWide;

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

  // Estado inicial de pin/largura + acompanha o breakpoint md.
  useEffect(() => {
    try {
      setIsOpen(localStorage.getItem(CHAT_OPEN_KEY) === "true");
      setIsPinned(localStorage.getItem(CHAT_PINNED_KEY) === "true");
      const w = parseInt(localStorage.getItem(CHAT_WIDTH_KEY) || "", 10);
      if (!Number.isNaN(w)) setPanelWidth(clampPanelWidth(w));
    } catch {
      // localStorage indisponível → mantém padrões
    }
    const mq = window.matchMedia(`(min-width: ${MD_BREAKPOINT}px)`);
    const onChange = () => setIsWide(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Encaixe: empurra o conteúdo principal abrindo espaço para o painel.
  useEffect(() => {
    const container = document.querySelector<HTMLElement>(".drawer-content");
    if (!container) return;
    if (docked) {
      container.style.paddingRight = `${panelWidth}px`;
    } else {
      container.style.paddingRight = "";
    }
    return () => {
      container.style.paddingRight = "";
    };
  }, [docked, panelWidth]);

  // Arrastar a alça de redimensionamento (resize mútuo).
  useEffect(() => {
    if (!isResizing) return;
    const onMove = (e: MouseEvent) => {
      setPanelWidth(clampPanelWidth(window.innerWidth - e.clientX));
    };
    const onUp = () => {
      setIsResizing(false);
      setPanelWidth((w) => {
        try {
          localStorage.setItem(CHAT_WIDTH_KEY, String(w));
        } catch {
          // ignore
        }
        return w;
      });
    };
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [isResizing]);

  const togglePin = () => {
    setIsPinned((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(CHAT_PINNED_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  // Fecha o menu de anexo ao clicar fora
  useEffect(() => {
    if (!attachMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (!attachMenuRef.current?.contains(e.target as Node)) {
        setAttachMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [attachMenuOpen]);

  // Mantém a ref sincronizada para o cleanup de desmontagem acessar a lista atual.
  useEffect(() => {
    attachmentsRef.current = attachments;
  }, [attachments]);

  // Revoga object URLs ao desmontar o componente (evita vazamento de memória).
  // Usa a ref para capturar os anexos atuais, não o snapshot do mount inicial.
  useEffect(() => {
    return () => {
      attachmentsRef.current.forEach((a) => URL.revokeObjectURL(a.url));
    };
  }, []);

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
      // Captura as URLs ANTES de limpar o estado. Não revoga aqui — as mesmas
      // strings são passadas para o bubble de mensagem enviada e continuam
      // válidas durante a sessão. O cleanup de desmontagem (via attachmentsRef)
      // não as alcançará porque já foram removidas do estado antes.
      const previews = attachments.map((a) => a.url);
      setInput("");
      setAttachments([]);
      await sendMultipart(form, label, previews);
      return;
    }

    const text = overrideMessage ?? input;
    if (!text.trim()) return;

    const userMsg: Message = {
      id: randomId(),
      role: "user",
      content: text.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);

    // Add placeholder for assistant response
    const assistantId = randomId();
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
            } else if (event.type === "done") {
              if (event.data_changed) notifyDataChanged();
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
          } else if (event.type === "done") {
            if (event.data_changed) notifyDataChanged();
          }
        } catch {
          // skip
        }
      }
    }
  };

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


  const handleImagePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(e.target.files);
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

  // Abre/fecha o chat persistindo o estado, para sobreviver ao reload das
  // páginas sem cards (mount.tsx) — senão o chat reabre fechado ("minimizado").
  const setOpen = (open: boolean) => {
    setIsOpen(open);
    try {
      localStorage.setItem(CHAT_OPEN_KEY, String(open));
    } catch {
      // localStorage indisponível → estado apenas em memória
    }
  };

  const handleClose = () => {
    setOpen(false);
    setIsMinimized(false);
  };

  // --- Collapsed state: floating button ---
  if (!isOpen) {
    return (
      <button
        onClick={() => setOpen(true)}
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
        {isWide && (
          <button
            onClick={togglePin}
            className="btn btn-ghost btn-xs text-neutral-content"
            title={isPinned ? "Desafixar (flutuante)" : "Fixar à direita"}
            aria-label={isPinned ? "Desafixar chat" : "Fixar chat à direita"}
            aria-pressed={isPinned}
          >
            <DockIcon active={isPinned} />
          </button>
        )}
        {!docked && (
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
      {/* Galeria/arquivo: sem capture, deixa o usuário escolher um arquivo existente */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={handleImagePick}
      />
      {/* Câmera: capture força a câmera no mobile */}
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={handleImagePick}
      />
      {/* Miniaturas das imagens em staging — aparecem acima da linha de input */}
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
          {/* Clipe de papel: abre menu com "Arquivo" ou "Câmera" */}
          <div className="relative" ref={attachMenuRef}>
            <button
              onClick={() => setAttachMenuOpen((v) => !v)}
              className="btn btn-sm btn-ghost btn-square"
              disabled={isStreaming || attachments.length >= MAX_IMAGES}
              title="Anexar"
              aria-label="Anexar arquivo ou foto"
              aria-haspopup="menu"
              aria-expanded={attachMenuOpen}
            >
              <PaperclipIcon />
            </button>
            {attachMenuOpen && (
              <ul className="menu menu-sm absolute bottom-full left-0 mb-1 z-10 w-40 rounded-box bg-base-100 border border-base-300 shadow-lg p-1">
                <li>
                  <button
                    onClick={() => {
                      setAttachMenuOpen(false);
                      fileInputRef.current?.click();
                    }}
                  >
                    <FileIcon />
                    Arquivo
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => {
                      setAttachMenuOpen(false);
                      cameraInputRef.current?.click();
                    }}
                  >
                    <CameraIcon />
                    Câmera
                  </button>
                </li>
              </ul>
            )}
          </div>
          {canRecord && (
            <button
              onClick={startRecording}
              className="btn btn-sm btn-ghost btn-square"
              disabled={isStreaming}
              title="Gravar áudio"
              aria-label="Gravar áudio"
            >
              <MicIcon />
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
            disabled={isStreaming || (!input.trim() && attachments.length === 0)}
          >
            →
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div
      className={
        docked
          ? "fixed top-0 right-0 h-screen z-50 flex flex-col bg-base-100 border-l border-base-300 shadow-xl"
          : `fixed bottom-6 right-6 z-50 max-w-[calc(100vw-2rem)] flex flex-col bg-base-100 border border-base-300 rounded-lg shadow-xl ${
              isMinimized ? "w-64 h-auto" : "w-96 h-[32rem] max-h-[calc(100vh-6rem)]"
            }`
      }
      style={docked ? { width: `${panelWidth}px` } : undefined}
    >
      {docked && (
        <div
          onMouseDown={(e) => {
            e.preventDefault();
            setIsResizing(true);
          }}
          className="absolute left-0 top-0 h-full w-1.5 -ml-0.5 cursor-col-resize hover:bg-accent/40 active:bg-accent/60 z-10"
          role="separator"
          aria-orientation="vertical"
          aria-label="Redimensionar painel do chat"
          title="Arraste para redimensionar"
        />
      )}
      {chatHeader}
      {(!isMinimized || docked) && (
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

// crypto.randomUUID() só existe em secure context (HTTPS ou localhost). No
// servidor dev acessado por IP via HTTP (ex.: http://192.168.1.7:8700) o
// contexto é inseguro e randomUUID fica undefined — chamá-lo lançava antes do
// fetch, então NADA era enviado (texto ou foto). getRandomValues existe mesmo
// em contexto inseguro, então geramos um UUID v4 a partir dele.
function randomId(): string {
  const c = typeof crypto !== "undefined" ? crypto : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const b = new Uint8Array(16);
  if (c && typeof c.getRandomValues === "function") {
    c.getRandomValues(b);
  } else {
    for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
  }
  b[6] = (b[6] & 0x0f) | 0x40; // versão 4
  b[8] = (b[8] & 0x3f) | 0x80; // variante RFC 4122
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0"));
  return `${h[0]}${h[1]}${h[2]}${h[3]}-${h[4]}${h[5]}-${h[6]}${h[7]}-${h[8]}${h[9]}-${h[10]}${h[11]}${h[12]}${h[13]}${h[14]}${h[15]}`;
}
