/**
 * The one way any surface asks the chat widget to open.
 *
 * A window event rather than a shared store: the chat is mounted as its own
 * React root by `mount.tsx`, so a card in a different root has no other way to
 * reach it, and a global is worse than an event because it would have to exist
 * before either root mounts.
 */
export function openChat(prompt?: string): void {
  window.dispatchEvent(new CustomEvent("open-chat", { detail: { prompt } }));
}
