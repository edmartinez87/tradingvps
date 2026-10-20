import { useState } from "react";
import { CalendarRange, Eye, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { http, errMsg, fmtDateTime } from "@/lib/api";
import { BTN_OUT } from "./SecuritySection";

const strip = (html) => html.replace(/<\/?b>/g, "");

export default function WeeklySummaryCard({ ready }) {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState("");
  const load = async () => {
    setBusy("preview");
    try {
      const { data } = await http.get("/weekly-summary");
      setPreview(data);
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };
  const send = async () => {
    setBusy("send");
    try {
      const { data } = await http.post("/weekly-summary/send");
      setPreview(data);
      toast.success("Resumen semanal enviado a Telegram");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };
  return (
    <div data-testid="weekly-summary-card" className="rounded-sm border border-[#1E293B] bg-[#0D111A] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-[200px] flex-1">
          <p className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-300"><CalendarRange className="h-3.5 w-3.5 text-amber-300" /> Resumen semanal · domingos 20:00 UTC</p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">PnL de la semana, mejores y peores pares, valor del filtro IA (operaciones sombra) y estado del plan. Usa el aviso «Resumen diario y semanal».{preview?.last_sent_at && <> Último envío: {fmtDateTime(preview.last_sent_at)}.</>}</p>
        </div>
        <div className="flex gap-2">
          <Button data-testid="weekly-preview-button" variant="outline" size="sm" onClick={load} disabled={busy === "preview"} className={BTN_OUT}>
            {busy === "preview" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Eye className="mr-1.5 h-3.5 w-3.5" />} Vista previa
          </Button>
          <Button data-testid="weekly-send-button" variant="outline" size="sm" onClick={send} disabled={busy === "send" || !ready} className={BTN_OUT}>
            {busy === "send" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Send className="mr-1.5 h-3.5 w-3.5" />} Enviar ahora
          </Button>
        </div>
      </div>
      {preview && (
        <pre data-testid="weekly-preview-text" style={{ fontFamily: "'IBM Plex Mono', 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', monospace" }} className="thin-scroll mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-sm border border-[#1E293B] bg-[#07090E] p-3 text-[11px] leading-relaxed text-slate-300">{strip(preview.text)}</pre>
      )}
    </div>
  );
}
