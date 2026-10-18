import { Area, AreaChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtUsd } from "@/lib/api";
import { fmtMonths } from "./PlanScenarios";

const PHASE_COLOR = { semilla: "#F7A600", crecimiento: "#10B981", consolidacion: "#38BDF8", ingreso: "#A78BFA" };

export default function PlanProjection({ projection: p }) {
  if (!p.reachable) {
    return (
      <div data-testid="plan-unreachable" className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-[12px] text-rose-300">
        Con este rendimiento la meta no se alcanza en 30 años. Primero el sistema debe demostrar expectativa positiva en paper trading; después el plan se recalcula solo.
      </div>
    );
  }
  const data = p.series.map((s) => ({ ...s, income: s.withdraw }));
  return (
    <div data-testid="plan-projection" className="space-y-3">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4">
        {[
          ["Tiempo hasta la meta", fmtMonths(p.months), "plan-months", "text-amber-400"],
          ["Capital objetivo", fmtUsd(p.target_capital, 0), "plan-target-capital", "text-slate-100"],
          ["Ingreso al llegar", `${fmtUsd(p.income_at_target, 0)}/mes`, "plan-income", "text-emerald-400"],
          ["Rendimiento usado", `${p.rate_pct}%/mes · ${(p.rate_pct * 1.5).toFixed(1)}% con 1.5% riesgo`, "plan-rate", "text-slate-100"],
        ].map(([l, v, id, cls]) => (
          <div key={id} className="bg-[#0D111A] px-3 py-2.5">
            <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p>
            <p data-testid={id} className={`num mt-1 text-sm font-semibold ${cls}`}>{v}</p>
          </div>
        ))}
      </div>
      <div className="h-52" data-testid="plan-chart">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 22, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="planFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#F7A600" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#F7A600" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="month" tick={{ fill: "#64748B", fontSize: 10, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} tickFormatter={(m) => `M${m}`} />
            <YAxis tick={{ fill: "#64748B", fontSize: 10, fontFamily: "IBM Plex Mono" }} width={64} axisLine={false} tickLine={false} tickFormatter={(v) => fmtUsd(v, 0)} />
            <ReferenceLine y={p.target_capital} stroke="#A78BFA" strokeDasharray="4 4" label={{ value: "Capital objetivo", fill: "#A78BFA", fontSize: 10, fontFamily: "IBM Plex Mono", position: "insideTopLeft" }} />
            {p.timeline.filter((t) => t.start_month > 0).map((t) => (
              <ReferenceLine key={t.key} x={t.start_month} stroke={PHASE_COLOR[t.key]} strokeDasharray="2 4" label={{ value: t.name, fill: PHASE_COLOR[t.key], fontSize: 9, fontFamily: "IBM Plex Mono", position: "top" }} />
            ))}
            <Tooltip contentStyle={{ background: "#0D111A", border: "1px solid #1E293B", fontFamily: "IBM Plex Mono", fontSize: 11 }}
              labelFormatter={(m) => `Mes ${m}`}
              formatter={(v, name) => [fmtUsd(v), { capital: "Capital", profit: "Ganancia del mes", income: "Retiro" }[name]]} />
            <Area type="monotone" dataKey="capital" stroke="#F7A600" strokeWidth={1.5} fill="url(#planFill)" isAnimationActive={false} />
            <Area type="monotone" dataKey="profit" stroke="transparent" fill="transparent" isAnimationActive={false} />
            <Area type="monotone" dataKey="income" stroke="transparent" fill="transparent" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
