import { ShieldCheck, Sparkles } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { Panel } from "./Panel";
import { fmtUsd, STRATEGY_LABELS } from "@/lib/api";

const Stat = ({ label, value, testId }) => (
  <div className="rounded-sm border border-[#1E293B] bg-[#07090E]/60 px-3 py-2">
    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
    <p data-testid={testId} className="num mt-0.5 text-sm font-semibold text-slate-100">{value}</p>
  </div>
);

export default function BotPanel({ settings: s, meta, account, equity }) {
  const info = meta?.strategy_info || {};
  const active = s.strategy === "all" ? Object.keys(info) : [s.strategy];
  const used = Math.min(100, Math.max(0, (-account.daily_pnl_pct / s.daily_loss_limit) * 100));
  const curve = equity.map((e) => ({ t: e.ts, v: e.equity }));

  return (
    <Panel testId="bot-plan-panel" title="Plan de trading" icon={ShieldCheck} className="lg:col-span-3" bodyClass="p-4 space-y-4 overflow-y-auto thin-scroll max-h-[540px]" delay={180}>
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">Estrategia activa · {s.timeframe}</p>
        <p data-testid="active-strategy-name" className="font-display mt-1 text-lg font-bold text-amber-400">{STRATEGY_LABELS[s.strategy]}</p>
        <ul className="mt-2 space-y-2">
          {active.map((k) => info[k] && (
            <li key={k} className="border-l-2 border-amber-500/40 pl-2.5">
              <p className="text-[13px] font-semibold text-slate-200">{info[k].name}</p>
              <p className="text-[12px] leading-relaxed text-slate-400">{info[k].rules}</p>
            </li>
          ))}
        </ul>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="Riesgo / op." value={`${s.risk_per_trade}%`} testId="plan-risk" />
        <Stat label="Máx. posiciones" value={s.max_positions} testId="plan-max-positions" />
        <Stat label="Apalancamiento" value={`${s.leverage}x`} testId="plan-leverage" />
        <Stat label="Límite diario" value={`-${s.daily_loss_limit}%`} testId="plan-daily-limit" />
      </div>

      <div data-testid="daily-loss-meter">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-wider">
          <span className="text-slate-500">Consumo límite diario</span>
          <span className={account.daily_paused ? "text-rose-400" : "text-slate-400"}>{account.daily_paused ? "Pausado" : `${used.toFixed(0)}%`}</span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[#1E293B]">
          <div className={`h-full transition-[width] duration-500 ${used > 70 ? "bg-rose-500" : used > 35 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${used}%` }} />
        </div>
      </div>

      <div data-testid="ai-config-card" className="rounded-sm border border-purple-500/30 bg-purple-500/[0.08] p-3">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-purple-300">
            <Sparkles className="h-3.5 w-3.5" /> Confirmación IA
          </span>
          <span data-testid="ai-status-label" className={`font-mono text-[10px] font-bold uppercase ${s.ai_enabled ? "text-purple-300" : "text-slate-500"}`}>
            {s.ai_enabled ? "Activa" : "Inactiva"}
          </span>
        </div>
        <p className="mt-1 text-[12px] leading-relaxed text-slate-400">
          Claude Sonnet revisa cada señal y solo se ejecuta si la aprueba con confianza ≥ {s.ai_min_confidence}%.
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-slate-500">
          <span>Curva de equidad</span>
          <span className="num text-slate-300">{fmtUsd(account.equity)}</span>
        </div>
        <div data-testid="equity-mini-chart" className="mt-2 h-24">
          {curve.length > 1 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={curve} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#F7A600" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#F7A600" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <YAxis hide domain={["dataMin - 5", "dataMax + 5"]} />
                <Tooltip contentStyle={{ background: "#0D111A", border: "1px solid #1E293B", fontFamily: "IBM Plex Mono", fontSize: 11 }}
                  labelFormatter={(l) => new Date(l).toLocaleString("es-ES")} formatter={(v) => [fmtUsd(v), "Equidad"]} />
                <Area type="monotone" dataKey="v" stroke="#F7A600" strokeWidth={1.5} fill="url(#eqFill)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <p className="pt-6 text-center text-[12px] text-slate-500">Se dibuja tras unos minutos de actividad</p>
          )}
        </div>
      </div>
    </Panel>
  );
}
