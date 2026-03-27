import { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { AlertData } from "../types";

interface Props {
  apiUrl: string;
}

const SEVERITY_STYLES: Record<
  string,
  { bg: string; border: string; text: string }
> = {
  danger: {
    bg: "bg-red-50",
    border: "border-l-red-500",
    text: "text-red-700",
  },
  warning: {
    bg: "bg-amber-50",
    border: "border-l-amber-500",
    text: "text-amber-800",
  },
  info: {
    bg: "bg-blue-50",
    border: "border-l-blue-500",
    text: "text-blue-700",
  },
  success: {
    bg: "bg-green-50",
    border: "border-l-green-500",
    text: "text-green-700",
  },
};

export default function AlertsCard({ apiUrl }: Props) {
  const [data, setData] = useState<AlertData[] | null>(null);

  useEffect(() => {
    fetchApi<AlertData[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Alertas</h3>
        <div className="space-y-2">
          {data.map((alert, i) => {
            const style =
              SEVERITY_STYLES[alert.severity] || SEVERITY_STYLES.info;
            return (
              <div
                key={i}
                className={`${style.bg} border-l-4 ${style.border} px-3 py-2 rounded-r text-xs font-medium ${style.text}`}
              >
                {alert.message}
              </div>
            );
          })}
          {data.length === 0 && (
            <div className="text-sm opacity-60 text-center py-4">
              Nenhum alerta este mês
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
