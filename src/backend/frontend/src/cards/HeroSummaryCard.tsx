import { formatBRL } from "../format";
import type { EvolutionPoint, SummaryData } from "../types";
import { useApiData } from "../useApiData";
import KpiTile from "./KpiTile";

interface Props {
  apiUrl: string;
  sparkUrl?: string;
}

export default function HeroSummaryCard({ apiUrl, sparkUrl }: Props) {
  const data = useApiData<SummaryData>(apiUrl);
  const evo = useApiData<EvolutionPoint[]>(sparkUrl ?? "");

  if (!data)
    return <div className="card bg-base-100 border border-base-300 shadow-md animate-pulse h-48" />;

  const balance = parseFloat(data.balance);
  const bDelta = data.delta_pct.balance;
  const up = (bDelta ?? 0) >= 0;

  const incomeSpark = evo?.map((p) => parseFloat(p.income)) ?? [];
  const expenseSpark = evo?.map((p) => parseFloat(p.expenses)) ?? [];

  return (
    <div className="card bg-gradient-to-br from-primary/10 to-base-100 border border-base-300 shadow-md">
      <div className="card-body p-5 gap-3">
        <div className="text-[11px] uppercase tracking-wide opacity-60">Saldo do mês</div>
        <div className="flex items-baseline gap-3 flex-wrap">
          <span
            className={`amount font-display text-4xl md:text-5xl font-bold leading-none ${
              balance >= 0 ? "text-base-content" : "text-error"
            }`}
          >
            {formatBRL(data.balance)}
          </span>
          {bDelta !== null && (
            <span className={`text-sm font-semibold ${up ? "text-success" : "text-error"}`}>
              {up ? "▲" : "▼"} {Math.abs(bDelta)}%
            </span>
          )}
        </div>

        <div className="flex gap-6 text-sm">
          <span className="opacity-70">
            Renda <span className="amount font-bold text-success">{formatBRL(data.income)}</span>
          </span>
          <span className="opacity-70">
            Gastos <span className="amount font-bold text-error">{formatBRL(data.expenses)}</span>
          </span>
        </div>

        {data.budget_pct !== null && (
          <div>
            <div className="text-[11px] opacity-60 mb-1">Orçamento utilizado: {data.budget_pct}%</div>
            <progress
              className={`progress w-full ${
                data.budget_pct > 100
                  ? "progress-error"
                  : data.budget_pct > 90
                    ? "progress-warning"
                    : "progress-accent"
              }`}
              value={Math.min(data.budget_pct, 100)}
              max="100"
            />
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-1">
          <KpiTile label="Renda" value={formatBRL(data.income)} deltaPct={data.delta_pct.income} spark={incomeSpark} />
          <KpiTile label="Gastos" value={formatBRL(data.expenses)} deltaPct={data.delta_pct.expenses} spark={expenseSpark} invertDelta />
          <KpiTile label="Retornos" value={formatBRL(data.returns)} deltaPct={data.delta_pct.returns} />
          <KpiTile
            label="Orçamento"
            value={data.budget_pct === null ? "—" : `${data.budget_pct}%`}
            deltaPct={null}
          />
        </div>
      </div>
    </div>
  );
}
