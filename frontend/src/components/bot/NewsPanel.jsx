import { useEffect, useState } from "react";
import { Newspaper, RefreshCw, Loader2, AlertTriangle, CalendarClock, ExternalLink, ShieldBan } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Empty } from "./Panel";
import { http, errMsg, fmtDateTime, fmtTime } from "@/lib/api";

const RISK = { BAJO: "text-emerald-300 border-emerald-500/40 bg-emerald-500/10", MEDIO: "text-amber-300 border-amber-500/40 bg-amber-500/10", ALTO: "text-rose-300 border-rose-500/40 bg-rose-500/10" };
const tone = (v) => (v > 15 ? "text-emerald-300" : v < -15 ? "text-rose-300" : "text-slate-200");
const mins = (iso) => Math.round((new Date(iso) - Date.now()) / 60000);
const when = (m) => (m < 0 ? `hace ${-m} min` : m < 120 ? `en ${m} min` : `en ${Math.round(m / 60)} h`);

const Sentiment = ({ value, testId }) => (
  <div data-testid={testId} className="flex items-center gap-2">
    <div className="relative h-1.5 w-28 overflow-hidden rounded-full bg-[#1E293B]">
      <div className="absolute left-1/2 top-0 h-full w-px bg-slate-500" />
      <div className={`absolute top-0 h-full ${value >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
        style={{ left: value >= 0 ? "50%" : `${50 + value / 2}%`, width: `${Math.abs(value) / 2}%` }} />
    </div>
    <span className={`num text-[12px] font-semibold ${tone(value)}`}>{value > 0 ? "+" : ""}{value}</span>
  </div>
);

export default function NewsPanel({ summary, symbols = [] }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => http.get("/news").then((r) => setData(r.data.latest)).catch(() => {});
  useEffect(() => { load(); }, [summary?.updated_at]);

  const refresh = async () => {
    setBusy(true);
    try {
      const { data: d } = await http.post("/news/refresh");
      setData(d.latest);
      toast.success("Noticias actualizadas");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-[12px] text-slate-400">
        {summary?.enabled === false ? "Agente de noticias desactivado en Ajustes." : "La IA lee titulares (CoinDesk, CoinTelegraph, The Block, Decrypt) y el calendario macro cada pocos minutos; el resultado entra en la evaluación de cada señal y puede pausar entradas o reducir el tamaño."}
      </p>
      <Button data-testid="news-refresh-button" size="sm" onClick={refresh} disabled={busy} variant="outline" className="h-7 border-[#1E293B] bg-transparent font-mono text-[10px] uppercase tracking-wider text-slate-200 hover:bg-[#111827]">
        {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />} Actualizar ahora
      </Button>
    </div>
  );
  if (!data) {
    return <div data-testid="news-panel" className="space-y-3 p-4">{header}<Empty testId="news-empty" text="Aún no hay análisis de noticias. Se genera automáticamente en el primer ciclo o con «Actualizar ahora»." /></div>;
  }
  const m = data.market;
  const now = Date.now();
  const events = (data.events || []).filter((e) => new Date(e.time) > now - 3 * 3600e3);
  return (
    <div data-testid="news-panel" className="space-y-4 p-4">
      {header}
      <div data-testid="news-market" className={`rounded-md border p-3.5 ${RISK[m.risk] || RISK.MEDIO}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Newspaper className="h-4 w-4" />
            <span className="font-display text-[14px] font-bold uppercase tracking-wider">Riesgo de mercado: <span data-testid="news-market-risk">{m.risk}</span></span>
          </div>
          <Sentiment value={m.sentiment} testId="news-market-sentiment" />
          <span className="font-mono text-[10px] text-slate-400">Actualizado {fmtTime(data.updated_at)}</span>
        </div>
        <p data-testid="news-market-summary" className="mt-2 text-[12.5px] leading-relaxed text-slate-200">{m.summary}</p>
        {summary?.blocked && (
          <p data-testid="news-blocked" className="mt-2 flex items-center gap-2 rounded-sm border border-rose-500/40 bg-rose-500/10 px-2 py-1.5 font-mono text-[11px] uppercase tracking-wider text-rose-300">
            <ShieldBan className="h-3.5 w-3.5" /> Nuevas entradas pausadas · {summary.blocked}
          </p>
        )}
      </div>

      {data.alerts?.length > 0 && (
        <div data-testid="news-alerts" className="space-y-2">
          {data.alerts.map((a) => (
            <div key={a.key} className={`flex gap-2 rounded-sm border px-3 py-2 ${a.severity === "CRITICA" ? "border-rose-500/50 bg-rose-500/10" : "border-orange-500/40 bg-orange-500/10"}`}>
              <AlertTriangle className={`mt-0.5 h-4 w-4 shrink-0 ${a.severity === "CRITICA" ? "text-rose-300" : "text-orange-300"}`} />
              <div>
                <p className="text-[12.5px] font-semibold text-slate-100"><span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">{a.severity} · {a.symbol} · </span>{a.title}</p>
                <p className="text-[11.5px] text-slate-300">{a.why}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div data-testid="news-pairs" className="rounded-sm border border-[#1E293B]">
          <p className="border-b border-[#1E293B] bg-[#0D111A] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">Pares con noticias relevantes</p>
          {Object.keys(data.pairs || {}).length === 0 ? <p className="p-3 text-[12px] text-slate-500">Sin noticias específicas de tus pares en las últimas horas.</p> : (
            <div className="divide-y divide-[#1E293B]/60">
              {Object.entries(data.pairs).map(([sym, p]) => (
                <div key={sym} data-testid={`news-pair-${sym}`} className="flex items-start gap-3 px-3 py-2">
                  <span className="font-display w-14 shrink-0 text-[13px] font-semibold text-slate-100">{sym.replace("USDT", "")}</span>
                  <span className={`shrink-0 rounded-sm border px-1.5 py-px font-mono text-[9px] uppercase ${RISK[p.risk] || RISK.MEDIO}`}>{p.risk}</span>
                  <Sentiment value={p.sentiment} />
                  <span className="text-[11.5px] leading-snug text-slate-400">{p.note}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div data-testid="news-events" className="rounded-sm border border-[#1E293B]">
          <p className="flex items-center gap-1.5 border-b border-[#1E293B] bg-[#0D111A] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500"><CalendarClock className="h-3 w-3" /> Calendario macro USD (72 h)</p>
          {!events.length ? <p className="p-3 text-[12px] text-slate-500">Sin eventos de impacto alto o medio en las próximas 72 h.</p> : (
            <div className="divide-y divide-[#1E293B]/60">
              {events.map((e, i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-2">
                  <span className={`shrink-0 rounded-sm border px-1.5 py-px font-mono text-[9px] uppercase ${e.impact === "ALTO" ? RISK.ALTO : RISK.MEDIO}`}>{e.impact}</span>
                  <span className="text-[12.5px] text-slate-100">{e.title}</span>
                  <span className="ml-auto shrink-0 font-mono text-[10px] text-slate-400">{fmtDateTime(e.time)} · {when(mins(e.time))}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div data-testid="news-headlines" className="rounded-sm border border-[#1E293B]">
        <p className="border-b border-[#1E293B] bg-[#0D111A] px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">Titulares recientes</p>
        <div className="thin-scroll max-h-[300px] divide-y divide-[#1E293B]/60 overflow-y-auto">
          {(data.headlines || []).map((h, i) => (
            <a key={i} href={h.link} target="_blank" rel="noreferrer" className="flex items-start gap-2 px-3 py-2 transition-colors hover:bg-[#111827]">
              <span className="w-24 shrink-0 font-mono text-[9px] uppercase tracking-wider text-slate-500">{h.source}<br />{fmtTime(h.published)}</span>
              <span className="flex-1 text-[12px] leading-snug text-slate-200">{h.title}</span>
              {h.symbols?.length > 0 && <span className="shrink-0 font-mono text-[9px] text-amber-300">{h.symbols.map((s) => s.replace("USDT", "")).join(" ")}</span>}
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-slate-600" />
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
