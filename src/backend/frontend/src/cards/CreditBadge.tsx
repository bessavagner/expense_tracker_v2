import { type Credits, formatRenewal } from "./useCredits";

interface Props {
  credits: Credits | null;
  onSelectTier: (tier: string) => void;
}

/**
 * The household's credit balance and the mode it spends them in.
 *
 * E07 S07-4: the allowance is visible, never silently applied. A user landing
 * on Essencial has to be able to see why and until when.
 *
 * Renders nothing until the balance loads — a placeholder that turns into a
 * number shifts the header on every mount for no information gained.
 */
export default function CreditBadge({ credits, onSelectTier }: Props) {
  if (!credits) return null;

  const { granted, remaining, renewsOn, tier, tiers } = credits;
  const current = tiers.find((t) => t.value === tier);
  const exhausted = remaining <= 0;
  const renewal = formatRenewal(renewsOn);

  return (
    <>
      <button
        className="btn btn-ghost btn-xs text-neutral-content gap-1"
        popovertarget="chat-credits-popover"
        style={{ anchorName: "--chat-credits-anchor" } as React.CSSProperties}
        aria-label={`Créditos: ${remaining} de ${granted}. Modo ${current?.label ?? tier}.`}
      >
        {/* Text, not colour, carries the state: "0" already says it, and the
            header sits on bg-neutral where a colour modifier would fight the
            surface it is printed on. */}
        <span className="font-mono text-xs tabular-nums">{remaining}</span>
        <span className="text-xs opacity-70">{current?.label ?? tier}</span>
      </button>

      <div
        className="dropdown dropdown-end card card-sm bg-base-100 text-base-content z-10 w-64 shadow-md"
        popover="auto"
        id="chat-credits-popover"
        style={{ positionAnchor: "--chat-credits-anchor" } as React.CSSProperties}
      >
        <div className="card-body gap-3">
          <div>
            <p className="text-sm font-semibold">
              {remaining} de {granted} créditos
            </p>
            <p className="text-xs opacity-70">Renovam em {renewal}</p>
          </div>

          <progress
            className="progress w-full"
            value={granted > 0 ? remaining : 0}
            max={granted > 0 ? granted : 1}
            aria-label={`${remaining} de ${granted} créditos restantes`}
          />

          {exhausted && (
            <div role="status" className="alert alert-soft alert-info p-2 text-xs">
              <span>
                Seus créditos acabaram. Continuo respondendo no modo Essencial até {renewal}.
              </span>
            </div>
          )}

          <div>
            <p className="mb-1 text-xs font-semibold opacity-70">Modo do assistente</p>
            <ul className="menu menu-sm w-full p-0">
              {tiers.map((option) => (
                <li key={option.value}>
                  <button
                    type="button"
                    className={option.value === tier ? "menu-active" : ""}
                    aria-current={option.value === tier ? "true" : undefined}
                    onClick={() => onSelectTier(option.value)}
                  >
                    {option.label}
                    {option.value === tier && (
                      <span className="badge badge-xs">atual</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <p className="text-xs opacity-60">
            Modos mais avançados gastam mais créditos por mensagem.
          </p>
        </div>
      </div>
    </>
  );
}
