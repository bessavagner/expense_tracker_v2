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
