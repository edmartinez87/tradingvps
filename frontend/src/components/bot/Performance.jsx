import { useEffect, useState } from "react";
import { Loader2, Power } from "lucide-react";
import { toast } from "sonner";
import { Empty } from "./Panel";
import { TH, TD } from "./PositionsTable";
import { http, fmtSignedUsd, fmtUsd, pnlClass, STRATEGY_LABELS, STRATEGY_KEYS, REASON_LABELS, HORIZON_LABELS, ENTRY_LABELS, activeStrategies } from "@/lib/api";
import ShadowStats from "./performance/ShadowStats";
import ExcursionStats from "./performance/ExcursionStats";

const SIDE = { long: "Long", short: "Short" };
const DECISION = { APROBADA: "Aprobadas IA", RECHAZADA: "Rechazadas IA", BLOQUEADA: "Bloqueadas riesgo", NOTICIAS: "Bloqueadas noticias", FUNDING: "Bloqueadas funding", REGIMEN: "Bloqueadas régimen BTC", ROTACION: "Bloqueadas rotación", EXPOSICION: "Bloqueadas exposición", ROLLOVER: "Bloqueadas rollover", VOLATILIDAD: "Bloqueadas volatilidad", ESTACIONAL: "Bloqueadas estacionalidad", REGIMEN_USD: "Bloqueadas régimen USD", FOMC: "Bloqueadas FOMC", MERCADO: "Mercado cerrado", SESION: "Fuera de sesión", SIN_IA: "Sin IA", ERROR: "Error IA" };

const Group = ({ title, label, rows, render = (k) => k, testId, isOn, onToggle }) => (
  <div data-testid={testId} className="overflow-hidden rounded-sm border border-[#1E293B]">
    <p className="border-b border-[#1E293B] bg-[#0D111A] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">{title}</p>
    <table className="w-full text-sm">
      <thead><tr><TH>{label}</TH><TH right>Ops</TH><TH right>Acierto</TH><TH right>PF</TH><TH right>PnL medio</TH><TH right>PnL</TH>{onToggle && <TH right>Estado</TH>}</tr></thead>
      <tbody className="num text-[12px]">
        {rows.map((r) => {
          const on = isOn ? isOn(r.key) : true;
          return (
            <tr key={r.key} data-testid={`perf-row-${r.key}`} className={`border-t border-[#1E293B]/60 transition-colors hover:bg-[#111827] ${on ? "" : "opacity-50"}`}>
              <TD className="font-display text-[13px] font-semibold text-slate-100">{render(r.key)}</TD>
              <TD right>{r.trades}</TD>
              <TD right>{r.win_rate}%</TD>
              <TD right className={r.profit_factor == null ? "text-slate-500" : r.profit_factor >= 1 ? "text-emerald-400" : "text-rose-400"}>{r.profit_factor ?? "∞"}</TD>
              <TD right className={pnlClass(r.avg_pnl)}>{fmtSignedUsd(r.avg_pnl)}</TD>
              <TD right className={`font-semibold ${pnlClass(r.pnl)}`}>{fmtSignedUsd(r.pnl)}</TD>
              {onToggle && (
                <TD right>
                  <button data-testid={`perf-toggle-${r.key}`} onClick={() => onToggle(r.key, !on)} title={on ? "Apagar: el bot dejará de operarlo" : "Volver a activar"}
                    className={`inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors ${on ? "border-emerald-500/40 text-emerald-300 hover:border-rose-500/50 hover:text-rose-300" : "border-slate-600 text-slate-400 hover:text-emerald-300"}`}>
                    <Power className="h-3 w-3" /> {on ? "Activo" : "Apagado"}
                  </button>
                </TD>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
);

export default function Performance({ tradeCount, settings, onSave, strategyKeys = STRATEGY_KEYS }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    http.get("/performance").then((r) => { setData(r.data); setError(false); }).catch(() => setError(true));
  }, [tradeCount]);

  if (error && !data) return <Empty testId="performance-error" text="No se pudo cargar el rendimiento. Reintentando en el próximo refresco." />;
  if (!data) return <div className="flex min-h-[120px] items-center justify-center text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  const sig = data.signals;
  const active = activeStrategies(settings, strategyKeys);
  const mk = data.maker;

  const toggleStrategy = (k, on) => {
    const next = on ? [...active, k] : active.filter((x) => x !== k);
    if (!next.length) return toast.error("Debe quedar al menos una estrategia activa");
    return onSave({ strategy: "all", disabled_strategies: strategyKeys.filter((x) => !next.includes(x)) });
  };
  const toggleSymbol = (s, on) => {
    const next = on ? [...settings.symbols, s] : settings.symbols.filter((x) => x !== s);
    if (!next.length) return toast.error("Debe quedar al menos un par activo");
    return onSave({ symbols: next });
  };

  return (
    <div data-testid="performance-panel" className="space-y-4 p-4">
      <p className="text-[12px] leading-relaxed text-slate-400">
        Rendimiento real del paper trading por estrategia y par. Apaga lo que pierde con el botón de cada fila (mínimo 30 operaciones antes de decidir); el bot deja de operarlo al instante y puedes reactivarlo cuando quieras.
      </p>
      <div data-testid="perf-signals" className="flex flex-wrap gap-2">
        {[["Señales", sig.total], ["Ejecutadas", sig.executed], ...Object.entries(sig.by_decision).map(([k, v]) => [DECISION[k] || k, v])].map(([l, v]) => (
          <div key={l} className="min-w-[130px] flex-1 rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2.5">
            <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p>
            <p className="num mt-1 text-base font-semibold text-slate-100">{v}</p>
          </div>
        ))}
      </div>
      {!data.by_strategy.length ? (
        <Empty testId="performance-empty" text="Aún no hay operaciones cerradas. Las estadísticas aparecerán con las primeras operaciones del bot." />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Group title="Por estrategia" label="Estrategia" rows={data.by_strategy} render={(k) => STRATEGY_LABELS[k] || k} testId="perf-by-strategy"
            isOn={(k) => active.includes(k)} onToggle={toggleStrategy} />
          <Group title="Por par" label="Par" rows={data.by_symbol} testId="perf-by-symbol" isOn={(k) => settings.symbols.includes(k)} onToggle={toggleSymbol} />
          <Group title="Por dirección" label="Lado" rows={data.by_side} render={(k) => SIDE[k] || k} testId="perf-by-side" />
          <Group title="Por tipo de salida" label="Salida" rows={data.by_reason} render={(k) => REASON_LABELS[k] || k} testId="perf-by-reason" />
          {data.by_horizon?.length > 0 && <Group title="Por horizonte" label="Horizonte" rows={data.by_horizon} render={(k) => HORIZON_LABELS[k] || k} testId="perf-by-horizon" />}
          {data.by_entry_type?.length > 0 && <Group title="Por tipo de entrada" label="Entrada" rows={data.by_entry_type} render={(k) => ENTRY_LABELS[k] || k} testId="perf-by-entry-type" />}
        </div>
      )}
      {mk && (mk.maker_fills > 0 || mk.market_fallbacks > 0 || mk.pending > 0) && (
        <div data-testid="perf-maker" className="flex flex-wrap gap-2">
          {[["Entradas maker llenadas", mk.maker_fills], ["A mercado tras esperar", mk.market_fallbacks], ["Tasa de llenado", mk.fill_rate == null ? "—" : `${mk.fill_rate}%`],
            ["Comisión ahorrada", fmtUsd(mk.fee_saved)], ["Órdenes límite en espera", mk.pending]].map(([l, v]) => (
            <div key={l} className="min-w-[130px] flex-1 rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2.5">
              <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p>
              <p className="num mt-1 text-base font-semibold text-slate-100">{v}</p>
            </div>
          ))}
        </div>
      )}
      <ExcursionStats data={data.excursion} />
      <ShadowStats data={data.shadow} />
    </div>
  );
}
