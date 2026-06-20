import {
  Area,
  AreaChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import EmptyState from "../components/EmptyState";
import { formatBRL, formatBRLCompact } from "../format";
import { CHART_COLORS } from "../theme";
import type { ProjectionCardData } from "../types";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

const REAL = CHART_COLORS[1]; // slate blue — posted trajectory
const EST = CHART_COLORS[0]; // teal (brand) — estimated trajectory

export default function ProjectionCard({ apiUrl }: Props) {
  const data = useApiData<ProjectionCardData>(apiUrl);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-64" />
    );

  if (!data.series || data.series.length === 0) {
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <h3 className="card-title text-sm">Projeção</h3>
          <EmptyState
            emoji="🔮"
            title="Sem projeção"
            description="Cadastre renda e gastos para projetar seu saldo futuro"
          />
        </div>
      </div>
    );
  }

  const chartData = data.series.map((p) => ({
    month: p.month.slice(5), // "2026-06" → "06"
    real: parseFloat(p.acumulado),
    estimado: parseFloat(p.acumulado_estimado),
  }));

  const saldoMes = parseFloat(data.saldo_mes);
  const delta = parseFloat(data.delta);
  const endEst = parseFloat(data.end_acumulado_estimado);
  const up = delta >= 0;

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="card-title text-sm">Projeção</h3>
          <a href="/projection/" className="link link-hover text-xs text-primary">
            Simular cenário →
          </a>
        </div>

        {/* Headline: estimated running balance at the end of the horizon */}
        <div className="mt-1">
          <div className="text-[11px] uppercase tracking-wide opacity-60">
            Acumulado estimado · {data.end_label}
          </div>
          <div className="flex items-baseline gap-2">
            <span
              className={`amount text-2xl font-bold ${endEst >= 0 ? "text-base-content" : "text-error"}`}
            >
              {formatBRL(data.end_acumulado_estimado)}
            </span>
            <span
              className={`text-xs font-semibold whitespace-nowrap ${up ? "text-success" : "text-error"}`}
            >
              {up ? "▲" : "▼"} {formatBRL(Math.abs(delta))}
            </span>
          </div>
          <div className="text-[11px] opacity-60">
            no horizonte de {data.series.length} meses, pelas suas médias de gasto
          </div>
        </div>

        {/* Saldo do mês corrente */}
        <div className="flex justify-between text-sm mt-2">
          <span className="opacity-70">Saldo deste mês</span>
          <span
            className={`amount font-bold whitespace-nowrap ${saldoMes >= 0 ? "text-success" : "text-error"}`}
          >
            {formatBRL(data.saldo_mes)}
          </span>
        </div>

        {/* Real vs estimated trajectory */}
        <ResponsiveContainer width="100%" height={132} className="mt-1">
          <AreaChart data={chartData} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="estFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={EST} stopOpacity={0.22} />
                <stop offset="100%" stopColor={EST} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis
              tick={{ fontSize: 10 }}
              width={52}
              tickFormatter={(v: number) => formatBRLCompact(v)}
            />
            <Tooltip
              formatter={(value: number, name: string) => [
                formatBRL(value),
                name === "estimado" ? "Estimado" : "Real",
              ]}
              labelFormatter={(l: string) => `Mês ${l}`}
            />
            <Area
              type="monotone"
              dataKey="estimado"
              name="estimado"
              stroke={EST}
              strokeWidth={2}
              fill="url(#estFill)"
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="real"
              name="real"
              stroke={REAL}
              strokeWidth={2}
              strokeDasharray="5 3"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>

        <div className="flex gap-4 text-[11px] opacity-70 -mt-1">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5" style={{ backgroundColor: EST }} />
            estimado
          </span>
          <span className="flex items-center gap-1">
            <span
              className="inline-block w-3 h-0 border-t-2 border-dashed"
              style={{ borderColor: REAL }}
            />
            real (lançado)
          </span>
        </div>
      </div>
    </div>
  );
}
