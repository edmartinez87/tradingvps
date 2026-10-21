import { fmtTime } from "@/lib/api";

export const AiHealthBanner = ({ ai }) => {
  const h = ai?.health;
  if (!h || h.ok !== false) return null;
  return (
    <div data-testid="ai-error-banner" className="rounded-md border border-rose-500/50 bg-rose-500/10 px-4 py-2 font-mono text-[11px] text-rose-200">
      <span className="font-semibold uppercase tracking-wider text-rose-300">IA sin servicio · {h.label}</span>
      {h.since ? ` · desde las ${fmtTime(h.since)}` : ""} · {ai.label}: {h.error}
      {" · "}las señales nuevas no se evalúan ni se operan hasta que la IA responda{h.alerted_at ? " · aviso enviado por Telegram" : ""}
    </div>
  );
};
