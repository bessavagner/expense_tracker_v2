import React, { useState } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import EmptyState from "../components/EmptyState";
import { formatBRL, formatBRLCompact } from "../format";
import { CHART_COLORS } from "../theme";
import type { DailyTrendData } from "../types";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

const MEDIAN = CHART_COLORS[0]; // teal — central line
const BAND = CHART_COLORS[1]; // slate blue — variability band
const PERIODS = [7, 15, 30, 90];

export default function DailyTrendCard({ apiUrl }: Props) {
  const [period, setPeriod] = useState(30);
  const data = useApiData<DailyTrendData>(`${apiUrl}?period=${period}`);

  const chartData =
    data?.series.map((p) => {
      const lo = parseFloat(p.p25);
      const hi = parseFloat(p.p75);
      return {
        date: p.date.slice(5), // "2025-07-03" → "07-03"
        median: parseFloat(p.median),
        base: lo, // transparent spacer
        band: hi - lo, // stacked filled band (p25..p75)
      };
    }) ?? [];

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="card-title text-sm">Tendência de gasto diário</h3>
          <select
            className="select select-bordered select-xs"
            value={period}
            onChange={(e) => setPeriod(Number(e.target.value))}
          >
            {PERIODS.map((p) => (
              <option key={p} value={p}>
                {p} dias
              </option>
            ))}
          </select>
        </div>

        {!data ? (
          <div className="h-48 animate-pulse" />
        ) : chartData.length === 0 ? (
          <EmptyState
            emoji="📈"
            title="Sem dados"
            description="Registre gastos para ver a tendência diária"
          />
        ) : (
          <>
            <div className="text-[11px] opacity-60 mt-1">
              mediana móvel (robusta a picos) · faixa = variação típica (p25–p75)
            </div>
            <ResponsiveContainer width="100%" height={240} className="mt-1">
              <ComposedChart
                data={chartData}
                margin={{ top: 6, right: 4, bottom: 0, left: 0 }}
              >
                <XAxis dataKey="date" tick={{ fontSize: 10 }} minTickGap={20} />
                <YAxis
                  tick={{ fontSize: 10 }}
                  width={52}
                  tickFormatter={(v: number) => formatBRLCompact(v)}
                />
                <Tooltip
                  formatter={
                    ((value: number, name: string) => {
                      if (name === "base" || name === "band") return null;
                      return [formatBRL(value), "Mediana"];
                    }) as React.ComponentProps<typeof Tooltip>["formatter"]
                  }
                  labelFormatter={(l: string) => `Dia ${l}`}
                />
                {/* transparent spacer up to p25 */}
                <Area
                  type="monotone"
                  dataKey="base"
                  stackId="band"
                  stroke="none"
                  fill="none"
                  isAnimationActive={false}
                  legendType="none"
                />
                {/* filled IQR band: p25..p75 */}
                <Area
                  type="monotone"
                  dataKey="band"
                  stackId="band"
                  stroke="none"
                  fill={BAND}
                  fillOpacity={0.18}
                  isAnimationActive={false}
                  legendType="none"
                />
                <Line
                  type="monotone"
                  dataKey="median"
                  name="median"
                  stroke={MEDIAN}
                  strokeWidth={2}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </>
        )}
      </div>
    </div>
  );
}
