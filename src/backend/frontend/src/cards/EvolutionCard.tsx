import { useEffect, useState } from "react";
import EmptyState from "../components/EmptyState";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { fetchApi } from "../api";
import { formatBRL, formatBRLCompact } from "../format";
import type { EvolutionPoint } from "../types";

interface Props {
  apiUrl: string;
}

export default function EvolutionCard({ apiUrl }: Props) {
  const [data, setData] = useState<EvolutionPoint[] | null>(null);

  useEffect(() => {
    fetchApi<EvolutionPoint[]>(apiUrl).then(setData);
  }, [apiUrl]);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-64" />
    );

  const hasData = data.some(d => parseFloat(d.expenses) > 0 || parseFloat(d.income) > 0);
  if (!hasData) {
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm">
        <div className="card-body p-4">
          <h3 className="card-title text-sm">Evolução</h3>
          <EmptyState emoji="📈" title="Sem movimentação" description="Adicione entradas para acompanhar a evolução mensal" />
        </div>
      </div>
    );
  }

  const chartData = data.map((d) => ({
    month: d.month.slice(5), // "2026-03" → "03"
    expenses: parseFloat(d.expenses),
    income: parseFloat(d.income),
  }));

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Evolução</h3>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData}>
            <XAxis dataKey="month" tick={{ fontSize: 11 }} />
            <YAxis
              tick={{ fontSize: 10 }}
              width={60}
              tickFormatter={(v: number) => formatBRLCompact(v)}
            />
            <Tooltip formatter={(value: number) => formatBRL(value)} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line
              type="monotone"
              dataKey="expenses"
              name="Gastos"
              stroke="#e94560"
              strokeWidth={2}
              dot={{ r: 3 }}
            />
            <Line
              type="monotone"
              dataKey="income"
              name="Renda"
              stroke="#16c79a"
              strokeWidth={2}
              strokeDasharray="6 3"
              dot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
