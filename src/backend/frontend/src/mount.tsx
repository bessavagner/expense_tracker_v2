import React from "react";
import { createRoot } from "react-dom/client";

// Card components will be imported here in Task 4
const COMPONENTS: Record<string, React.ComponentType<{ apiUrl: string }>> = {};

function mountAll() {
  const elements = document.querySelectorAll("[data-react-component]");
  elements.forEach((el) => {
    const name = el.getAttribute("data-react-component");
    const apiUrl = el.getAttribute("data-api-url") || "";
    if (name && COMPONENTS[name]) {
      const Component = COMPONENTS[name];
      const root = createRoot(el);
      root.render(<Component apiUrl={apiUrl} />);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAll);
} else {
  mountAll();
}
