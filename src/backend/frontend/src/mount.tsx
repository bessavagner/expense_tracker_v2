import React from "react";
import { createRoot } from "react-dom/client";
import SummaryCard from "./cards/SummaryCard";
import TopCategoriesCard from "./cards/TopCategoriesCard";
import EvolutionCard from "./cards/EvolutionCard";
import AlertsCard from "./cards/AlertsCard";
import RecentEntriesCard from "./cards/RecentEntriesCard";
import InstallmentsCard from "./cards/InstallmentsCard";
import ChatWidget from "./cards/ChatWidget";

const COMPONENTS: Record<string, React.ComponentType<{ apiUrl: string }>> = {
  SummaryCard,
  TopCategoriesCard,
  EvolutionCard,
  AlertsCard,
  RecentEntriesCard,
  InstallmentsCard,
  ChatWidget,
};

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

// Reatividade após o assistente alterar dados (item #5): o dashboard tem cards
// React que se reatualizam sozinhos (useApiData). Páginas sem cards (entradas,
// consolidado, cockpit) recarregam para refletir a mudança imediatamente.
window.addEventListener("data-changed", () => {
  const hasCards = document.querySelector('[data-react-component$="Card"]');
  if (!hasCards) window.location.reload();
});
