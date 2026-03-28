import { useSyncExternalStore, useCallback } from "react";

const STORAGE_KEY = "expense_tracker_chat_pinned";

let isPinned = localStorage.getItem(STORAGE_KEY) === "true";
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return isPinned;
}

function setPinned(value: boolean) {
  isPinned = value;
  localStorage.setItem(STORAGE_KEY, String(value));
  listeners.forEach((l) => l());
  // Notify Alpine.js
  window.dispatchEvent(
    new CustomEvent(value ? "chat:pin" : "chat:unpin", {
      detail: { width: 380 },
    }),
  );
}

export function useChatPinned() {
  const pinned = useSyncExternalStore(subscribe, getSnapshot, () => false);
  const toggle = useCallback(() => setPinned(!pinned), [pinned]);
  return { isPinned: pinned, setIsPinned: setPinned, togglePinned: toggle };
}
