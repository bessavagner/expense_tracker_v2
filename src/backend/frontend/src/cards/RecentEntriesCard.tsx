import { useEffect, useState } from "react";
import { fetchApi } from "../api";
import type { EntryData } from "../types";

interface Props {
  apiUrl: string;
}

export default function RecentEntriesCard({ apiUrl }: Props) {
  const [data, setData] = useState<EntryData[] | null>(null);

  useEffect(() => {
    fetchApi<EntryData[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Últimas Entradas</h3>
        <div className="space-y-1">
          {data.map((entry, i) => {
            const amount = parseFloat(entry.amount);
            return (
              <div
                key={i}
                className="flex justify-between text-xs py-1 border-b border-base-200 last:border-0"
              >
                <span className={amount < 0 ? "text-success" : "opacity-70"}>
                  {entry.date} {entry.description}
                </span>
                <span
                  className={`font-bold ${amount < 0 ? "text-success" : "text-error"}`}
                >
                  R$ {entry.amount}
                </span>
              </div>
            );
          })}
        </div>
        <a
          href="/entries/"
          className="text-xs text-primary font-bold text-center mt-2 block"
        >
          Ver todas →
        </a>
      </div>
    </div>
  );
}
