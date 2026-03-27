import { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { SummaryData } from "../types";

interface Props {
  apiUrl: string;
}

export default function SummaryCard({ apiUrl }: Props) {
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    fetchApi<SummaryData>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  const balance = parseFloat(data.balance);

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Resumo Mensal</h3>
        <div className="space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="opacity-70">Renda</span>
            <span className="font-bold text-success">R$ {data.income}</span>
          </div>
          <div className="flex justify-between">
            <span className="opacity-70">Gastos</span>
            <span className="font-bold text-error">R$ {data.expenses}</span>
          </div>
          <div className="flex justify-between">
            <span className="opacity-70">Retornos</span>
            <span className="text-success">R$ {data.returns}</span>
          </div>
          <div className="divider my-1" />
          <div className="flex justify-between font-bold">
            <span>Saldo</span>
            <span className={balance >= 0 ? "text-success" : "text-error"}>
              R$ {data.balance}
            </span>
          </div>
          <div className="mt-2">
            <div className="text-xs opacity-60 mb-1">
              Orçamento utilizado: {data.budget_pct}%
            </div>
            <progress
              className={`progress w-full ${data.budget_pct > 100 ? "progress-error" : data.budget_pct > 90 ? "progress-warning" : "progress-accent"}`}
              value={data.budget_pct}
              max="100"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
