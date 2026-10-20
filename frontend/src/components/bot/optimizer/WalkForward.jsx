import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ShieldCheck, ShieldAlert, ShieldX, HelpCircle, Hourglass } from "lucide-react";
import { fmtUsd, fmtDateTime } from "@/lib/api";
import WalkForwardFolds from "./WalkForwardFolds";

export const VERDICT = {
  ROBUSTO: { label: "Robusto", cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300", Icon: ShieldCheck },
  DUDOSO: { label: "Dudoso", cls: "border-amber-500/40 bg-amber-500/10 text-amber-300", Icon: ShieldAlert },
  SOBREAJUSTADO: { label: "Sobreajustado", cls: "border-rose-500/40 bg-rose-500/10 text-rose-300", Icon: ShieldX },
  NO_RENTABLE: { label: "No rentable", cls: "border-rose-500/40 bg-rose-500/10 text-rose-300", Icon: ShieldX },
  INSUFICIENTE: { label: "Datos insuficientes", cls: "border-slate-500/40 bg-slate-500/10 text-slate-300", Icon: Hourglass },
};

export const VerdictBadge = ({ verdict, testId, size = "sm" }) => {
  const v = VERDICT[verdict] || { label: verdict, cls: "border-slate-500/40 text-slate-300", Icon: HelpCircle };
  return (
    <span data-testid={testId} className={`inline-flex items-center gap-1 rounded-sm border px-2 font-mono uppercase tracking-wider ${v.cls} ${size === "lg" ? "py-1 text-[11px]" : "py-0.5 text-[10px]"}`}>
      <v.Icon className={size === "lg" ? "h-3.5 w-3.5" : "h-3 w-3"} /> {v.label}
    </span>
  );
};

const sign = (v, d = 3) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}`);
const Cell = ({ label, value, hint, cls = "text-slate-100", testId }) => (
  <div className="bg-[#0D111A] px-3 py-2.5">
    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p data-testid={testId} className={`num mt-1 text-sm font-semibold ${cls}`}>{value}</p>
    {hint && <p className="text-[10px] text-slate-500">{hint}</p>}
  </div>
);

export default function WalkForward({ res }) {
  const { oos, baseline_oos: base, wfe, verdict } = res;
  const curve = res.oos_curve.map((p, i) => ({ i, time: p.time, opt: p.equity, base: res.baseline_curve[Math.min(i, res.baseline_curve.length - 1)]?.equity }));
  const folds = res.folds.length;
  const good = (a, b) => (a > b ? "text-emerald-400" : a < b ? "text-rose-400" : "text-slate-100");
  return (
    <div data-testid="walk-forward" className="space-y-3 rounded-md border border-sky-500/30 bg-sky-500/[0.05] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-[240px] flex-1">
          <p className="font-display text-[15px] font-bold text-sky-200">Validación walk-forward · {res.symbol}</p>
          <p className="mt-1 text-[12px] leading-relaxed text-slate-400">
            {folds} tramo{folds !== 1 ? "s" : ""}: en cada uno se optimiza con hasta {res.is_len} velas pasadas (in-sample) y se opera a ciegas las {res.oos_len} siguientes (out-of-sample).
            Fuera de muestra: {fmtDateTime(res.oos_start)} → {fmtDateTime(res.period_end)} · {res.candles} velas {res.timeframe}.
          </p>
        </div>
        <VerdictBadge verdict={verdict} testId="wf-verdict" size="lg" />
      </div>
      <p data-testid="wf-verdict-text" className="text-[12px] leading-relaxed text-slate-200">{res.verdict_text}</p>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-3 lg:grid-cols-6">
        <Cell label="Expectativa OOS (R)" value={sign(oos.expectancy_r)} hint={`in-sample ${sign(res.is_expectancy_r)} · base ${sign(base.expectancy_r)}`} cls={good(oos.expectancy_r, 0)} testId="wf-oos-expectancy" />
        <Cell label="Eficiencia WF" value={wfe == null ? "—" : wfe.toFixed(2)} hint="OOS / in-sample · ≥ 0.5 aceptable" cls={wfe == null ? "text-slate-400" : wfe >= 0.5 ? "text-emerald-400" : "text-rose-400"} testId="wf-wfe" />
        <Cell label="Profit factor OOS" value={oos.profit_factor ?? "—"} hint={`línea base ${base.profit_factor ?? "—"}`} cls={good(oos.profit_factor, 1)} testId="wf-oos-pf" />
        <Cell label="Retorno OOS" value={`${sign(oos.return_pct, 2)}%`} hint={`línea base ${sign(base.return_pct, 2)}%`} cls={good(oos.return_pct, base.return_pct)} testId="wf-oos-return" />
        <Cell label="Operaciones OOS" value={`${oos.trades} · ${oos.win_rate}%`} hint={`línea base ${base.trades} · ${base.win_rate}%`} testId="wf-oos-trades" />
        <Cell label="Parámetros" value={res.params_stable ? "Estables" : "Inestables"} hint={`${res.params_unique} combinación${res.params_unique !== 1 ? "es" : ""} en ${folds} tramos`} cls={res.params_stable ? "text-emerald-400" : "text-amber-400"} testId="wf-params" />
      </div>

      {curve.length > 1 && (
        <div className="h-44" data-testid="wf-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve} margin={{ top: 8, right: 24, left: 0, bottom: 0 }}>
              <XAxis dataKey="time" tick={{ fill: "#64748B", fontSize: 10, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} tickFormatter={(t) => t.slice(5, 10)} minTickGap={40} />
              <YAxis tick={{ fill: "#64748B", fontSize: 10, fontFamily: "IBM Plex Mono" }} width={60} axisLine={false} tickLine={false} tickFormatter={(v) => fmtUsd(v, 0)} domain={["auto", "auto"]} />
              <ReferenceLine y={curve[0].opt} stroke="#334155" strokeDasharray="4 4" />
              <Tooltip contentStyle={{ background: "#0D111A", border: "1px solid #1E293B", fontFamily: "IBM Plex Mono", fontSize: 11 }}
                labelFormatter={(t) => fmtDateTime(t)} formatter={(v, name) => [fmtUsd(v), name === "opt" ? "Optimizado (OOS)" : "Línea base (OOS)"]} />
              <Line type="monotone" dataKey="base" stroke="#64748B" strokeWidth={1.2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="opt" stroke="#38BDF8" strokeWidth={1.6} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <WalkForwardFolds folds={res.folds} />
    </div>
  );
}
