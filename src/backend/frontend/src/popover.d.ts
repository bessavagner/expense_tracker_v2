/**
 * Popover API + CSS anchor positioning attributes, for React 18's typings.
 *
 * daisyUI's dropdown is built on the native popover API, and React 18's DOM
 * typings predate it (React 19 ships these). React itself passes unknown
 * lowercase attributes straight through to the DOM, so this is a
 * type-level-only gap — deleting the file breaks `tsc`, not the browser.
 *
 * Remove when the project moves to React 19.
 */

import "react";

declare module "react" {
  interface HTMLAttributes<T> {
    popover?: "auto" | "manual" | "";
    popovertarget?: string;
    popovertargetaction?: "toggle" | "show" | "hide";
  }

  interface CSSProperties {
    anchorName?: string;
    positionAnchor?: string;
  }
}
