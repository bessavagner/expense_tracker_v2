import { useState } from "react";
import type { AlertData } from "../types";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

// Theme-aware severity styling (DaisyUI semantic colors adapt to light/dark).
const SEVERITY_BORDER: Record<string, string> = {
  danger: "border-l-error bg-error/10",
  warning: "border-l-warning bg-warning/10",
  info: "border-l-info bg-info/10",
  success: "border-l-success bg-success/10",
};

const SEVERITY_RANK: Record<string, number> = {
  danger: 0,
  warning: 1,
  info: 2,
  success: 3,
};

const LIMIT = 5;

export default function AlertsCard({ apiUrl }: Props) {
  const data = useApiData<AlertData[]>(apiUrl);
  const [expanded, setExpanded] = useState(false);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  // Most severe first, then collapse the tail.
  const alerts = [...data].sort(
    (a, b) =>
      (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9),
  );
  const shown = expanded ? alerts : alerts.slice(0, LIMIT);

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Alertas</h3>
        <div className="space-y-2">
          {shown.map((alert, i) => {
            const border = SEVERITY_BORDER[alert.severity] || SEVERITY_BORDER.info;
            return (
              <div
                key={i}
                className={`${border} border-l-4 px-3 py-2 rounded-r text-xs font-medium text-base-content`}
              >
                {alert.message}
              </div>
            );
          })}

          {alerts.length > LIMIT && (
            <button
              className="btn btn-ghost btn-xs w-full"
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded ? "ver menos" : `ver todos (${alerts.length})`}
            </button>
          )}

          {alerts.length === 0 && (
            <div className="text-sm opacity-60 text-center py-4">
              Nenhum alerta este mês
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
