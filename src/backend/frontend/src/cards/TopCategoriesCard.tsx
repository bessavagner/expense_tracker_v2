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
          {data.map((cat, i) => (
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
                    width: `${(parseFloat(cat.amount) / maxAmount) * 100}%`,
                    backgroundColor: CHART_COLORS[i % CHART_COLORS.length],
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
