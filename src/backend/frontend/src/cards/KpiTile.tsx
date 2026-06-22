import { Line, LineChart, ResponsiveContainer } from "recharts";
import type { SparkPoint } from "../types";
import { CHART_COLORS } from "../theme";

interface Props {
  label: string;
  value: string; // already formatted (e.g. "R$ 1.234,56" or "198%")
  deltaPct: number | null;
  spark?: number[];
  invertDelta?: boolean;
}

export default function KpiTile({ label, value, deltaPct, spark, invertDelta }: Props) {
  const up = (deltaPct ?? 0) >= 0;
  // "good" = green. For inverted metrics (Gastos), up is bad.
  const good = invertDelta ? !up : up;
  const sparkData: SparkPoint[] = (spark ?? []).map((v) => ({ v }));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm tile-hover min-w-0">
      <div className="card-body p-3 gap-1">
        <div className="text-[11px] uppercase tracking-wide opacity-60">{label}</div>
        <div className="amount text-xl lg:text-2xl font-bold leading-none truncate">{value}</div>
        <div className="flex items-center justify-between gap-2">
          {deltaPct === null ? (
            <span className="text-[11px] opacity-50">—</span>
          ) : (
            <span className={`text-[11px] font-semibold ${good ? "text-success" : "text-error"}`}>
              {up ? "▲" : "▼"} {Math.abs(deltaPct)}%
            </span>
          )}
          {sparkData.length > 1 && (
            <div className="h-6 w-16">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sparkData}>
                  <Line
                    type="monotone"
                    dataKey="v"
                    stroke={CHART_COLORS[0]}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
