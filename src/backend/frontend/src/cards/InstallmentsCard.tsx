import { useEffect, useState } from "react";
import { fetchApi } from "../api";
import { formatBRL } from "../format";
import type { InstallmentsResponse } from "../types";

interface Props {
  apiUrl: string;
}

const LIMIT = 5;

export default function InstallmentsCard({ apiUrl }: Props) {
  const [data, setData] = useState<InstallmentsResponse | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    fetchApi<InstallmentsResponse>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  // Show the most significant installments first; collapse the long tail.
  const plans = [...data.plans].sort(
    (a, b) => parseFloat(b.amount) - parseFloat(a.amount),
  );
  const shown = expanded ? plans : plans.slice(0, LIMIT);

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Parcelas Ativas</h3>
        <div className="space-y-1">
          {shown.map((plan, i) => (
            <div
              key={i}
              className="flex justify-between text-xs py-1 border-b border-base-200 last:border-0"
            >
              <span className="opacity-70">
                {plan.description}{" "}
                <span className="text-base-content/50">
                  ({plan.current}/{plan.total})
                </span>
              </span>
              <span className="amount font-bold whitespace-nowrap">{formatBRL(plan.amount)}</span>
            </div>
          ))}

          {plans.length > LIMIT && (
            <button
              className="btn btn-ghost btn-xs w-full mt-1"
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded ? "ver menos" : `ver todas (${plans.length})`}
            </button>
          )}

          {plans.length > 0 && (
            <>
              <div className="divider my-1" />
              <div className="flex justify-between text-xs font-bold">
                <span>Total este mês</span>
                <span className="amount text-error whitespace-nowrap">
                  {formatBRL(data.monthly_total)}
                </span>
              </div>
            </>
          )}
          {plans.length === 0 && (
            <div className="text-sm opacity-60 text-center py-4">
              Nenhuma parcela ativa este mês
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
