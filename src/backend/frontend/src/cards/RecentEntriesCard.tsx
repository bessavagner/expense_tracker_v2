import { formatBRL } from "../format";
import type { EntryData, LedgerElsewhere } from "../types";
import EmptyState from "../components/EmptyState";
import { openChat } from "../chat";
import { useApiData } from "../useApiData";

interface Props {
  apiUrl: string;
  /** Same query string the card is rendered with, so "elsewhere" means
   *  "not the month on screen" rather than "not this calendar month". */
  elsewhereUrl?: string;
}

export default function RecentEntriesCard({ apiUrl, elsewhereUrl }: Props) {
  const data = useApiData<EntryData[]>(apiUrl);
  const elsewhere = useApiData<LedgerElsewhere>(elsewhereUrl ?? "");

  if (!data)
    return (
      <div className="card bg-base-200 border border-base-200 animate-pulse h-48" />
    );

  if (data.length === 0) {
    // D05: a household with entries in another month is not an empty ledger, and
    // telling it that its first receipt did nothing is what made the walkthrough
    // participant re-enter the same purchase by hand.
    const other = elsewhere?.has_any ? elsewhere.nearest : null;
    return (
      <div className="card bg-base-200 border border-base-200">
        <div className="card-body p-4">
          <h3 className="text-[11px] uppercase tracking-wide opacity-60">Últimas Entradas</h3>
          {other ? (
            <EmptyState
              emoji="📅"
              title="Nada neste mês"
              description={`Seus lançamentos mais próximos estão em ${other.label}.`}
              actionLabel={`Ver ${other.label}`}
              actionHref={`/?year=${other.year}&month=${other.month}`}
            />
          ) : (
            <EmptyState
              emoji="📷"
              title="Nada lançado ainda"
              description="Fotografe um cupom fiscal — o app lê os itens, separa por categoria e lança tudo aqui."
              actionLabel="Fotografar um cupom"
              onAction={() => openChat()}
            />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="card bg-base-200 border border-base-200">
      <div className="card-body p-4">
        <h3 className="text-[11px] uppercase tracking-wide opacity-60">Últimas Entradas</h3>
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
