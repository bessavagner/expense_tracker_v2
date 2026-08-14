import { useCallback, useEffect, useState } from "react";

/** E07 S07-4: the household's allowance, so a degrade is never a surprise. */
export interface Credits {
  granted: number;
  remaining: number;
  renewsOn: string;
  tier: string;
  tiers: { value: string; label: string }[];
}

interface UsagePayload {
  granted: number;
  remaining: number;
  renews_on: string;
  tier: string;
  tiers: { value: string; label: string }[];
}

function csrfToken(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

/**
 * Reads `usage/` and lets the household switch tier.
 *
 * `refresh` is exposed rather than polled on a timer: the balance only moves
 * when this user takes a turn, so the widget refreshes after each completed
 * turn and otherwise costs nothing.
 *
 * Every failure resolves to `null` credits rather than an error state. The
 * badge is informational — a chat that refuses to render because the balance
 * endpoint hiccuped would be a worse product than one that quietly hides a
 * number.
 */
export function useCredits(apiUrl: string) {
  const [credits, setCredits] = useState<Credits | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${apiUrl}usage/`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const data: UsagePayload = await response.json();
      setCredits({
        granted: data.granted,
        remaining: data.remaining,
        renewsOn: data.renews_on,
        tier: data.tier,
        tiers: data.tiers,
      });
    } catch {
      // Informational only — see the docstring.
    }
  }, [apiUrl]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setTier = useCallback(
    async (tier: string) => {
      // Optimistic: the selector has to feel instant, and `refresh` below is
      // what makes the displayed state true again if the POST was rejected.
      setCredits((prev) => (prev ? { ...prev, tier } : prev));
      try {
        await fetch(`${apiUrl}tier/`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
          },
          credentials: "same-origin",
          body: JSON.stringify({ tier }),
        });
      } catch {
        // fall through to refresh
      }
      void refresh();
    },
    [apiUrl, refresh],
  );

  return { credits, refresh, setTier };
}

/** "2026-09-01" -> "01/09/2026", without dragging in a date library. */
export function formatRenewal(iso: string): string {
  const [year, month, day] = iso.split("-");
  return day && month && year ? `${day}/${month}/${year}` : iso;
}
