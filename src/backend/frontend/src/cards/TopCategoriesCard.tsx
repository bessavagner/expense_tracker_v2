import { formatBRL } from "../format";
import type { CategoryData } from "../types";
import EmptyState from "../components/EmptyState";
import { CHART_COLORS } from "../theme";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

export default function TopCategoriesCard({ apiUrl }: Props) {
  const data = useApiData<CategoryData[]>(apiUrl);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  if (data.length === 0) {
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <h3 className="card-title text-sm">Top Categorias</h3>
          <EmptyState emoji="🏷️" title="Sem categorias" description="Categorize suas despesas para ver o ranking" actionHref="/settings/" actionLabel="Configurações" />
        </div>
      </div>
    );
  }

  const maxAmount = Math.max(...data.map((d) => parseFloat(d.amount)), 1);

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Top Categorias</h3>
        <div className="space-y-2">
          {data.map((cat, i) => {
            const amount = parseFloat(cat.amount);
            const avg = cat.avg_3m !== null ? parseFloat(cat.avg_3m) : null;
            // ▲ acima da média habitual (atenção) / ▼ abaixo (ok). 5% de folga.
            const above = avg !== null && amount > avg * 1.05;
            const below = avg !== null && amount < avg * 0.95;
            return (
              <div key={cat.name}>
                <div className="flex justify-between text-xs mb-0.5">
                  <span className="opacity-70">{cat.name}</span>
                  <span className="amount font-bold whitespace-nowrap">
                    {formatBRL(cat.amount)}
                  </span>
                </div>
                <div className="bg-base-200 rounded h-2.5">
                  <div
                    className="h-full rounded"
                    style={{
                      width: `${(amount / maxAmount) * 100}%`,
                      backgroundColor: CHART_COLORS[i % CHART_COLORS.length],
                    }}
                  />
                </div>
                {avg !== null && (
                  <div className="text-[10px] opacity-60 mt-0.5 flex justify-end gap-1">
                    <span>média 3m {formatBRL(cat.avg_3m as string)}</span>
                    {above && <span className="text-error font-semibold">▲ acima</span>}
                    {below && <span className="text-success font-semibold">▼ abaixo</span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
