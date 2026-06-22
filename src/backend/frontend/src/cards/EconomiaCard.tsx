import { formatBRL } from "../format";
import type { DiverseSavingsData } from "../types";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
}

export default function EconomiaCard({ apiUrl }: Props) {
  const data = useApiData<DiverseSavingsData>(apiUrl);

  if (!data)
    return (
      <div className="card bg-base-100 border border-base-300 shadow-sm animate-pulse h-48" />
    );

  const economia = parseFloat(data.economia);
  const saved = economia >= 0;

  return (
    <div className="card bg-base-100 border border-base-300 shadow-sm">
      <div className="card-body p-4">
        <h3 className="card-title text-sm">Economia do mês</h3>

        {!data.has_baseline ? (
          <div className="text-xs opacity-60 mt-2">
            Sem base histórica ainda — registre mais meses de diversas.
          </div>
        ) : (
          <>
            <div className="text-[11px] uppercase tracking-wide opacity-60 mt-1">
              {saved ? "Economizou em diversas" : "Acima do habitual"}
            </div>
            <div
              className={`amount text-2xl font-bold ${saved ? "text-success" : "text-warning"}`}
            >
              {formatBRL(Math.abs(economia))}
            </div>
            <div className="text-[11px] opacity-60">
              habitual {formatBRL(data.baseline)} · gasto {formatBRL(data.actual)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
