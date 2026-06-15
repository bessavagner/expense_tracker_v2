import { formatBRL } from "../format";
import type { EntryData } from "../types";
import EmptyState from "../components/EmptyState";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

export default function RecentEntriesCard({ apiUrl }: Props) {
  const data = useApiData<EntryData[]>(apiUrl);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  if (data.length === 0) {
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <h3 className="card-title text-sm">Últimas Entradas</h3>
          <EmptyState emoji="📝" title="Nenhuma entrada recente" description="Adicione sua primeira entrada para começar" actionHref="/entries/" actionLabel="Ver entradas" />
        </div>
      </div>
    );
  }

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
                  className={`font-bold whitespace-nowrap ${amount < 0 ? "text-success" : "text-error"}`}
                >
                  {formatBRL(entry.amount)}
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
