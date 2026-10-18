import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { SideBadge } from "./Panel";
import { http, errMsg, fmtUsd, fmtSignedUsd, fmtPrice, fmtDateTime, pnlClass, STRATEGY_LABELS, REASON_LABELS } from "@/lib/api";

const Field = ({ label, value, onChange, options, testId, render = (o) => o }) => (
  <div className="min-w-[140px] flex-1">
    <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger data-testid={testId} className="h-9 border-[#1E293B] bg-[#07090E] font-mono text-xs"><SelectValue /></SelectTrigger>
      <SelectContent className="border-[#1E293B] bg-[#0D111A]">
        {options.map((o) => <SelectItem key={o} value={o} className="font-mono text-xs">{render(o)}</SelectItem>)}
      </SelectContent>
    </Select>
  </div>
);

const Metric = ({ label, value, tone, testId }) => (
  <div className="bg-[#0D111A] px-3 py-2.5">
    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p data-testid={testId} className={`num mt-1 text-base font-semibold ${tone != null ? pnlClass(tone) : "text-slate-100"}`}>{value}</p>
  </div>
);

export default function Backtest({ meta, settings }) {
  const [form, setForm] = useState({ symbol: settings.symbols[0], strategy: settings.strategy, timeframe: settings.timeframe });
  const [res, setRes] = useState(null);
  const [loading, setLoading] = useState(false);
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  const run = async () => {
    setLoading(true);
    try {
      const { data } = await http.post("/backtest", { ...form, risk_per_trade: settings.risk_per_trade, leverage: settings.leverage });
      setRes(data);
    } catch (e) {
      toast.error(`Backtest falló: ${errMsg(e)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div data-testid="backtest-panel" className="space-y-4 p-4">
      <p className="text-[12px] leading-relaxed text-slate-400">
        Evalúa la estrategia sobre las últimas 1.000 velas reales (sin filtro IA ni TF superior) con el mismo plan de riesgo: {settings.risk_per_trade}% por operación, {settings.leverage}x, comisiones 0.055% y trailing stop.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Par" value={form.symbol} onChange={set("symbol")} options={meta?.symbols || []} testId="backtest-symbol-select" />
        <Field label="Estrategia" value={form.strategy} onChange={set("strategy")} options={meta?.strategies || []} testId="backtest-strategy-select" render={(o) => STRATEGY_LABELS[o]} />
        <Field label="Temporalidad" value={form.timeframe} onChange={set("timeframe")} options={meta?.timeframes || []} testId="backtest-timeframe-select" />
        <Button data-testid="backtest-run-button" onClick={run} disabled={loading} className="h-9 bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">
          {loading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="mr-1.5 h-3.5 w-3.5" />} Ejecutar
        </Button>
      </div>

      {res && (
        <div data-testid="backtest-results" className="space-y-4">
          <p className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
            {res.symbol} · {STRATEGY_LABELS[res.strategy]} · {res.timeframe} · {fmtDateTime(res.period_start)} → {fmtDateTime(res.period_end)}
          </p>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4">
            <Metric label="Retorno" value={`${res.return_pct > 0 ? "+" : ""}${res.return_pct}%`} tone={res.return_pct} testId="backtest-return" />
            <Metric label="Operaciones" value={res.total_trades} testId="backtest-trades" />
            <Metric label="Tasa de acierto" value={`${res.win_rate}%`} testId="backtest-winrate" />
            <Metric label="Profit factor" value={res.profit_factor} testId="backtest-pf" />
            <Metric label="Máx. drawdown" value={`${res.max_drawdown}%`} tone={res.max_drawdown ? -1 : 0} testId="backtest-dd" />
            <Metric label="Equidad final" value={fmtUsd(res.final_equity)} testId="backtest-final" />
            <Metric label="Ganancia media" value={fmtSignedUsd(res.avg_win)} tone={res.avg_win} testId="backtest-avg-win" />
            <Metric label="Pérdida media" value={fmtSignedUsd(res.avg_loss)} tone={res.avg_loss} testId="backtest-avg-loss" />
          </div>
          <div className="h-40" data-testid="backtest-equity-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={res.equity_curve} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="btFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={res.return_pct >= 0 ? "#10B981" : "#EF4444"} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={res.return_pct >= 0 ? "#10B981" : "#EF4444"} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" hide />
                <YAxis domain={["dataMin - 20", "dataMax + 20"]} tick={{ fill: "#64748B", fontSize: 10, fontFamily: "IBM Plex Mono" }} width={60} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: "#0D111A", border: "1px solid #1E293B", fontFamily: "IBM Plex Mono", fontSize: 11 }}
                  labelFormatter={(l) => fmtDateTime(l)} formatter={(v) => [fmtUsd(v), "Equidad"]} />
                <Area type="monotone" dataKey="equity" stroke={res.return_pct >= 0 ? "#10B981" : "#EF4444"} strokeWidth={1.5} fill="url(#btFill)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="max-h-56 overflow-y-auto thin-scroll rounded-sm border border-[#1E293B]">
            {res.trades.slice(0, 20).map((t, i) => (
              <div key={i} className="flex items-center justify-between gap-3 border-b border-[#1E293B]/60 px-3 py-2 font-mono text-[11px]">
                <span className="text-slate-500">{fmtDateTime(t.opened_at)}</span>
                <SideBadge side={t.side} />
                <span className="hidden text-slate-400 sm:inline">{STRATEGY_LABELS[t.strategy]}</span>
                <span className="text-slate-300">{fmtPrice(t.entry)} → {fmtPrice(t.exit)}</span>
                <span className="text-slate-500">{REASON_LABELS[t.reason]}</span>
                <span className={pnlClass(t.pnl)}>{fmtSignedUsd(t.pnl)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
