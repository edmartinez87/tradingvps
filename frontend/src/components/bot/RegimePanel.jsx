import { useEffect, useState } from "react";
import { Loader2, RefreshCw, X } from "lucide-react";
import { toast } from "sonner";
import { http, errMsg, fmtPrice, fmtDateTime, STRATEGY_LABELS } from "@/lib/api";
import { TH, TD } from "./PositionsTable";

const BIAS = { long: ["Solo largos", "text-emerald-300 border-emerald-500/40"], short: ["Solo cortos", "text-rose-300 border-rose-500/40"], both: ["Ambos", "text-slate-300 border-slate-600"] };
const fmtVol = (v) => (v >= 1e9 ? `$${(v / 1e9).toFixed(2)} B` : `$${(v / 1e6).toFixed(0)} M`);

const Stat = ({ label, value, testId, cls = "text-slate-100" }) => (
  <div data-testid={testId} className="min-w-[140px] flex-1 rounded-sm border border-[#1E293B] bg-[#0D111A] px-3 py-2.5">
    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p className={`num mt-1 text-base font-semibold ${cls}`}>{value}</p>
  </div>
);

export default function RegimePanel({ settings, onSave }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => http.get("/market/context").then((r) => setData(r.data)).catch(() => toast.error("No se pudo cargar el contexto de mercado"));
  useEffect(() => { load(); }, [settings.btc_regime_filter, settings.rotation_enabled, settings.entry_order_type]);

  const refresh = async () => {
    setBusy(true);
    try { await http.post("/rotation/refresh"); await load(); toast.success("Ranking semanal recalculado"); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const cancelPending = async () => {
    try { const r = await http.delete("/pending-entries"); await load(); toast.success(`${r.data.cancelled} orden(es) límite cancelada(s)`); } catch (e) { toast.error(errMsg(e)); }
  };

  if (!data) return <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin text-slate-500" /></div>;
  const rg = data.regime, rot = data.rotation, bull = rg.state === "ALCISTA";
  const Toggle = ({ k, label, testId }) => (
    <button data-testid={testId} onClick={() => onSave({ [k]: !settings[k] })}
      className={`rounded-sm border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${settings[k] ? "border-emerald-500/40 text-emerald-300" : "border-slate-600 text-slate-400"}`}>
      {label}: {settings[k] ? "Activo" : "Apagado"}
    </button>
  );

  return (
    <div data-testid="regime-panel" className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">Régimen BTC diario · filtro global</p>
        <Toggle k="btc_regime_filter" label="Filtro régimen" testId="regime-toggle" />
      </div>
      <div className="flex flex-wrap gap-2">
        <Stat label="Estado" value={rg.state} testId="regime-state" cls={rg.state === "N/D" ? "text-slate-400" : bull ? "text-emerald-400" : "text-rose-400"} />
        <Stat label="BTC" value={fmtPrice(rg.price)} testId="regime-price" />
        <Stat label={`SMA ${rg.sma} (1D)`} value={fmtPrice(rg.sma_value)} testId="regime-sma" />
        <Stat label="Distancia" value={rg.distance_pct == null ? "—" : `${rg.distance_pct > 0 ? "+" : ""}${rg.distance_pct}%`} testId="regime-distance" cls={bull ? "text-emerald-400" : "text-rose-400"} />
      </div>
      <p className="text-[11px] text-slate-500">
        {bull ? "BTC sobre su media diaria: las estrategias de corto plazo solo abren largos; cortos solo si BTC cae bajo la media." : rg.state === "BAJISTA" ? "BTC bajo su media diaria: las estrategias de corto plazo solo abren cortos." : "Sin datos suficientes de BTC: el filtro no bloquea."}
        {" "}Las estrategias de largo plazo (LP) tienen su propio filtro diario y no se ven afectadas.
      </p>

      <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
          Rotación semanal · momentum {rot.lookback_days} d ponderado por volumen · recalculado {fmtDateTime(rot.computed_at)} · próximo {fmtDateTime(rot.next_at)}
        </p>
        <div className="flex gap-2">
          <Toggle k="rotation_enabled" label="Rotación" testId="rotation-toggle" />
          <button data-testid="rotation-refresh" onClick={refresh} disabled={busy} className="inline-flex items-center gap-1 rounded-sm border border-slate-600 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-slate-300 transition-colors hover:border-amber-500/50 hover:text-amber-300 disabled:opacity-50">
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Recalcular
          </button>
        </div>
      </div>
      <div className="overflow-hidden rounded-sm border border-[#1E293B]">
        <table className="w-full text-sm">
          <thead><tr><TH>#</TH><TH>Par</TH><TH right>Rend. {rot.lookback_days} d</TH><TH right>Volumen</TH><TH right>Tamaño</TH><TH right>Sesgo</TH></tr></thead>
          <tbody className="num text-[12px]">
            {rot.ranking.map((r) => (
              <tr key={r.symbol} data-testid={`rotation-row-${r.symbol}`} className="border-t border-[#1E293B]/60 transition-colors hover:bg-[#111827]">
                <TD className="text-slate-500">{r.rank}</TD>
                <TD className="font-display text-[13px] font-semibold text-slate-100">{r.symbol.replace("USDT", "")}</TD>
                <TD right className={r.ret_pct >= 0 ? "text-emerald-400" : "text-rose-400"}>{r.ret_pct > 0 ? "+" : ""}{r.ret_pct}%</TD>
                <TD right>{fmtVol(r.volume_usd)}</TD>
                <TD right className={r.size_factor < 1 ? "text-amber-300" : ""}>×{r.size_factor}</TD>
                <TD right><span className={`rounded-sm border px-1.5 py-0.5 font-mono text-[10px] ${BIAS[r.bias][1]}`}>{BIAS[r.bias][0]}</span></TD>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-500">Ranking relativo entre tus pares (un líder puede tener rendimiento negativo en una semana bajista). Tercio superior: solo largos · tercio inferior: solo cortos · volumen bajo la mediana: tamaño ×0,75. Solo afecta a estrategias de corto plazo.</p>

      <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
          Entradas · {data.entry_order_type === "maker" ? `límite maker (espera hasta ${data.maker_wait_bars} velas, luego a mercado)` : "a mercado"} · máx. {data.max_long_positions} posiciones LP
        </p>
        <div className="flex gap-2">
          <button data-testid="entry-type-toggle" onClick={() => onSave({ entry_order_type: data.entry_order_type === "maker" ? "market" : "maker" })}
            className={`rounded-sm border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${data.entry_order_type === "maker" ? "border-emerald-500/40 text-emerald-300" : "border-slate-600 text-slate-400"}`}>
            Maker: {data.entry_order_type === "maker" ? "Activo" : "Apagado"}
          </button>
          {data.pending_entries.length > 0 && (
            <button data-testid="pending-cancel-all" onClick={cancelPending} className="inline-flex items-center gap-1 rounded-sm border border-rose-500/40 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-rose-300 hover:bg-rose-500/10">
              <X className="h-3 w-3" /> Cancelar límites
            </button>
          )}
        </div>
      </div>
      {data.pending_entries.length > 0 ? (
        <div data-testid="pending-entries" className="overflow-hidden rounded-sm border border-[#1E293B]">
          <table className="w-full text-sm">
            <thead><tr><TH>Par</TH><TH>Lado</TH><TH>Estrategia</TH><TH right>Precio límite</TH><TH right>Velas</TH><TH>Creada</TH></tr></thead>
            <tbody className="num text-[12px]">
              {data.pending_entries.map((p) => (
                <tr key={p.id} data-testid={`pending-row-${p.id}`} className="border-t border-[#1E293B]/60">
                  <TD className="font-display text-[13px] font-semibold text-slate-100">{p.symbol.replace("USDT", "")}</TD>
                  <TD className={p.side === "long" ? "text-emerald-400" : "text-rose-400"}>{p.side === "long" ? "Long" : "Short"}</TD>
                  <TD>{STRATEGY_LABELS[p.strategy] || p.strategy}</TD>
                  <TD right>{fmtPrice(p.limit_price)}</TD>
                  <TD right>{p.bars_waited}/{p.max_bars}</TD>
                  <TD className="text-slate-400">{fmtDateTime(p.created_at)}</TD>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p data-testid="pending-empty" className="text-[11px] text-slate-500">Sin órdenes límite en espera.</p>
      )}
    </div>
  );
}
