export interface SummaryData {
  income: string;
  expenses: string;
  returns: string;
  balance: string;
  budget_pct: number | null;
}

export interface CategoryData {
  name: string;
  amount: string;
  pct: number;
  avg_3m: string | null;
}

export interface ProjectionPoint {
  month: string;
  acumulado: string;
  acumulado_estimado: string;
}

export interface ProjectionCardData {
  month_label: string;
  end_label: string;
  saldo_mes: string;
  acumulado: string;
  acumulado_estimado: string;
  end_acumulado_estimado: string;
  delta: string;
  series: ProjectionPoint[];
}

export interface EvolutionPoint {
  month: string;
  expenses: string;
  income: string;
}

export interface AlertData {
  severity: "danger" | "warning" | "info" | "success";
  message: string;
}

export interface EntryData {
  date: string;
  description: string;
  amount: string;
  category: string;
}

export interface InstallmentData {
  description: string;
  current: number;
  total: number;
  amount: string;
}

export interface InstallmentsResponse {
  plans: InstallmentData[];
  monthly_total: string;
}

export interface DiverseSavingsData {
  baseline: string;
  actual: string;
  economia: string;
  has_baseline: boolean;
}

export interface DailyTrendPoint {
  date: string;
  median: string;
  p25: string;
  p75: string;
}

export interface DailyTrendData {
  period: number;
  series: DailyTrendPoint[];
}
