import { Globe2, Clock, Filter } from "lucide-react";
import { fmtDateTime } from "@/lib/api";

export default function SessionsStrip({ hours, allowed = [] }) {
  if (!hours) return null;
  const filtered = allowed.length > 0;
  const tradable = !filtered || hours.sessions.some((s) => s.open && allowed.includes(s.id));
  return (
    <div data-testid="sessions-strip" className="panel rise flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5" style={{ animationDelay: "30ms" }}>
      <span data-testid="market-open-badge" className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${
        hours.open ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-slate-600 bg-slate-500/10 text-slate-300"}`}>
        <Globe2 className="h-3 w-3" /> {hours.open ? "Mercado forex abierto" : "Mercado forex cerrado"}
      </span>
      <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-500">
        <Clock className="h-3 w-3" /> {hours.open ? "Cierra" : "Abre"} {fmtDateTime(hours.next_change)}
        {hours.closing_soon && <span className="ml-1 rounded-sm border border-amber-500/40 px-1.5 text-amber-300">cierre de semana inminente</span>}
      </span>
      {filtered && hours.open && (
        <span data-testid="session-filter-badge" className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${
          tradable ? "border-amber-500/40 bg-amber-500/10 text-amber-300" : "border-[#1E293B] text-slate-500"}`}>
          <Filter className="h-3 w-3" /> {tradable ? "Sesión operable" : "Fuera de las sesiones permitidas · sin nuevas entradas"}
        </span>
      )}
      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        {hours.sessions.map((s) => {
          const ok = !filtered || allowed.includes(s.id);
          return (
            <span key={s.id} data-testid={`session-${s.id}`} title={`Hora local ${s.local}${filtered ? (ok ? " · sesión permitida" : " · fuera del filtro de sesiones") : ""}`}
              className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-[10px] ${s.open ? "border-sky-500/40 bg-sky-500/10 text-sky-300" : "border-[#1E293B] text-slate-500"} ${ok ? "" : "opacity-60 line-through"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${s.open ? "bg-sky-400" : "bg-slate-600"}`} /> {s.name} <span className="num opacity-70">{s.local}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}
