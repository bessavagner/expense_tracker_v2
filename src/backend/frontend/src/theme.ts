// Chart palette for the "ledger" design system.
// Recharts sets colors as SVG attributes (CSS variables don't resolve there),
// so these are concrete, harmonious tones tuned to read well on both the warm
// light theme and the dark slate theme. Teal leads (brand); the rest are a
// curated earthy set rather than a saturated rainbow.

export const CHART_COLORS = [
  "#1f9e91", // teal — brand
  "#3f6fa8", // slate blue
  "#c9913f", // warm gold
  "#c4623f", // clay / terracotta
  "#7a8b4f", // sage
  "#8a5a9c", // muted plum
];

// Semantic series for the evolution chart.
export const SERIES = {
  expense: "#c4623f", // outflow — warm clay (calmer than neon red)
  income: "#1f9e91", // inflow — brand teal
};
