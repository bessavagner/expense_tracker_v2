import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
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
    return <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />;

  if (data.length === 0) {
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <h3 className="text-[11px] uppercase tracking-wide opacity-60">Top Categorias</h3>
          <EmptyState
            emoji="🏷️"
            title="Sem categorias"
            description="Categorize suas despesas para ver o ranking"
            actionHref="/settings/"
            actionLabel="Configurações"
          />
        </div>
      </div>
    );
  }

  const slices = data.map((c) => ({ name: c.name, value: parseFloat(c.amount), pct: c.pct }));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm tile-hover">
      <div className="card-body p-4">
        <h3 className="text-[11px] uppercase tracking-wide opacity-60">Top Categorias</h3>
        <div className="flex items-center gap-3">
          <div className="w-32 h-32 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={40}
                  outerRadius={62}
                  paddingAngle={2}
                  isAnimationActive={false}
                >
                  {slices.map((s, i) => (
                    <Cell
                      key={s.name}
                      fill={
                        s.name === "Outros"
                          ? "var(--color-base-300, #ccc)"
                          : CHART_COLORS[i % CHART_COLORS.length]
                      }
                    />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => formatBRL(v)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-1 text-xs">
            {slices.map((s, i) => (
              <li key={s.name} className="flex items-center gap-2">
                <span
                  className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                  style={{
                    backgroundColor:
                      s.name === "Outros" ? "#bbb" : CHART_COLORS[i % CHART_COLORS.length],
                  }}
                />
                <span className="opacity-70 truncate">{s.name}</span>
                <span className="ml-auto amount font-bold whitespace-nowrap">{formatBRL(s.value)}</span>
                <span className="opacity-50 w-10 text-right">{s.pct}%</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
