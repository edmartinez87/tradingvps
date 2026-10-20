import { useEffect, useRef } from "react";
import { TerminalSquare, Trash2 } from "lucide-react";
import { Panel } from "./Panel";
import { fmtTime } from "@/lib/api";

const LEVEL_CLS = {
  INFO: "text-slate-400",
  SCAN: "text-sky-400",
  SIGNAL: "text-amber-400",
  AI_EVAL: "text-purple-400",
  ORDER: "text-emerald-400",
  RISK: "text-orange-400",
  PLAN: "text-teal-300",
  NEWS: "text-fuchsia-300",
  ERROR: "text-rose-400",
};

export default function Terminal({ logs, onClear }) {
  const ref = useRef(null);
  const lines = [...logs].reverse();
  const newest = logs[0]?.id;
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [newest]);

  return (
    <Panel testId="terminal-panel" title="Registro del bot" icon={TerminalSquare} className="lg:col-span-7" delay={380}
      actions={
        <button data-testid="clear-logs-button" onClick={onClear} className="inline-flex items-center gap-1 font-mono text-[10px] uppercase text-slate-500 transition-colors hover:text-rose-300">
          <Trash2 className="h-3 w-3" /> Limpiar
        </button>
      }>
      <div ref={ref} data-testid="terminal-log" className="terminal h-[440px] overflow-y-auto thin-scroll px-4 py-3 font-mono text-[11.5px] leading-6">
        {lines.length ? lines.map((l) => (
          <div key={l.id} className="flex gap-3 whitespace-pre-wrap">
            <span className="shrink-0 text-slate-600">{fmtTime(l.ts)}</span>
            <span className={`w-[68px] shrink-0 ${LEVEL_CLS[l.level] || "text-slate-400"}`}>[{l.level}]</span>
            <span className="text-slate-300">{l.message}</span>
          </div>
        )) : <span className="text-slate-600">$ esperando eventos...</span>}
        <span className="inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-amber-400/80" />
      </div>
    </Panel>
  );
}
