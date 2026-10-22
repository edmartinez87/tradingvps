import { useState } from "react";
import * as Icons from "lucide-react";
import { Check } from "lucide-react";
import { CodeBlock } from "./CodeBlock";
import { STEPS } from "./vpsContent";

const KEY = "vps_steps_done";
const Icon = ({ name, className }) => { const C = Icons[name] || Icons.Circle; return <C className={className} />; };
const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; } };

function Step({ step, n, done, onToggle }) {
  return (
    <li data-testid={`vps-step-${step.id}`} className={`relative rounded-md border p-5 transition-colors ${done ? "border-emerald-500/30 bg-emerald-500/[0.04]" : "border-[#1E293B] bg-[#0D111A]"}`}>
      <div className="flex items-start gap-3">
        <span className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border font-mono text-[12px] font-bold ${done ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"}`}>{n}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 font-display text-[14px] font-semibold text-slate-100"><Icon name={step.icon} className="h-4 w-4 text-emerald-400" /> {step.title}</h3>
            <button type="button" data-testid={`vps-step-${step.id}-done`} onClick={onToggle}
              className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${done ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300" : "border-[#1E293B] text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300"}`}>
              <span className={`inline-flex h-3.5 w-3.5 items-center justify-center rounded-[3px] border ${done ? "border-emerald-400 bg-emerald-400 text-[#07090E]" : "border-slate-500"}`}>{done && <Check className="h-3 w-3" strokeWidth={3} />}</span>
              {done ? "Hecho" : "Marcar hecho"}
            </button>
          </div>
          {step.text && <p className="mt-2 text-[12.5px] leading-relaxed text-slate-300">{step.text}</p>}
          {step.bullets && (
            <ul className="mt-2 space-y-1.5">
              {step.bullets.map((b, i) => <li key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-slate-300"><span className="mt-[8px] h-1 w-1 shrink-0 rounded-full bg-emerald-400" />{b}</li>)}
            </ul>
          )}
          {step.code && <div className="mt-3 space-y-2">{step.code.map((c, i) => <CodeBlock key={i} cmd={c.cmd} where={c.where} testId={`vps-code-${step.id}-${i}`} />)}</div>}
          {step.after && <p className="mt-3 rounded-sm border border-[#1E293B] bg-[#07090E] px-3 py-2 text-[11.5px] leading-relaxed text-slate-400">{step.after}</p>}
        </div>
      </div>
    </li>
  );
}

export function VpsSteps() {
  const [done, setDone] = useState(load);
  const toggle = (id) => {
    const next = done.includes(id) ? done.filter((x) => x !== id) : [...done, id];
    setDone(next); localStorage.setItem(KEY, JSON.stringify(next));
  };
  const pct = Math.round((done.length / STEPS.length) * 100);
  return (
    <section data-testid="vps-steps" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-400">Guía paso a paso</p>
          <h2 className="font-display mt-1 text-lg font-bold text-slate-50">Instalación en {STEPS.length} pasos</h2>
        </div>
        <div className="min-w-[220px] flex-1 sm:max-w-xs">
          <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-slate-500"><span>Progreso</span><span data-testid="vps-progress">{done.length} de {STEPS.length}</span></div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#1E293B]"><div className="h-full rounded-full bg-emerald-400 transition-[width] duration-500" style={{ width: `${pct}%` }} /></div>
        </div>
      </div>
      <ol className="space-y-3">
        {STEPS.map((s, i) => <Step key={s.id} step={s} n={i + 1} done={done.includes(s.id)} onToggle={() => toggle(s.id)} />)}
      </ol>
    </section>
  );
}
