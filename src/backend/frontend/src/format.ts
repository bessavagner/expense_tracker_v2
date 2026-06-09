const BRL = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

/** Format a numeric value (string like "4000.00" or number) as pt-BR BRL: "R$ 4.000,00". */
export function formatBRL(value: string | number): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (!Number.isFinite(n)) return "—";
  return BRL.format(n);
}

const COMPACT = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Compact BRL for chart axis ticks: "R$ 9 mil". */
export function formatBRLCompact(value: number): string {
  if (!Number.isFinite(value)) return "";
  return COMPACT.format(value);
}
