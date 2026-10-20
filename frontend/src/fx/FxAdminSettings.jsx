import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { http, errMsg } from "@/lib/api";
import SecuritySection from "@/components/bot/admin/SecuritySection";
import AiSection from "@/components/bot/admin/AiSection";
import TelegramSection from "@/components/bot/admin/TelegramSection";
import AccountSection from "@/components/bot/admin/AccountSection";
import HfmSection from "./HfmSection";
import FxNewsSection from "./FxNewsSection";
import LiveModeSection from "@/components/bot/admin/LiveModeSection";
import { fmtDateTime } from "@/lib/api";

const HFM_LIVE_LABELS = {
  exchange: "HFM",
  liveDesc: (d) => <>Operando con dinero real en HFM <span className="text-slate-200">{d.env}</span> vía MetaApi desde {fmtDateTime(d.live_since)}. Las órdenes a mercado llevan SL/TP adjuntos, el trailing stop se actualiza en el bróker y los cierres por SL/TP se detectan desde el historial de la cuenta.</>,
  paperDesc: () => <>Deja el bot en paper hasta que el historial demuestre expectativa positiva. Cuando los requisitos estén en verde, pasa a real: el bot usará la misma estrategia, el mismo riesgo y la equidad real de tu cuenta HFM (apalancamiento del bróker) para dimensionar cada orden en lotes.</>,
  dialogDesc: (d) => <>El bot enviará órdenes reales a HFM <b className="text-slate-200">{d.env}</b> con una equidad verificada de <b className="text-slate-200">{(d.verified_equity || 0).toLocaleString("en-US", { minimumFractionDigits: 2 })} {d.currency}</b>. Riesgo por operación, lote mínimo, límites diarios y filtros de sesión y noticias se aplican tal cual.</>,
  resetLabel: "Reiniciar estadísticas con la equidad real de HFM",
};

export default function FxAdminSettings({ account, refresh }) {
  const [config, setConfig] = useState(null);

  const load = useCallback(() => http.get("/config").then((r) => setConfig(r.data)).catch((e) => toast.error(errMsg(e))), []);
  useEffect(() => { load(); }, [load]);

  const save = async (body, okMsg = "Ajustes guardados") => {
    try {
      const { data } = await http.put("/config", body);
      setConfig(data);
      toast.success(okMsg);
      refresh?.();
      return true;
    } catch (e) {
      toast.error(errMsg(e));
      return false;
    }
  };

  if (!config) return <div data-testid="fx-admin-loading" className="flex min-h-[300px] items-center justify-center text-slate-500"><Loader2 className="h-5 w-5 animate-spin" /></div>;
  return (
    <div data-testid="fx-admin-settings" className="space-y-4">
      <div>
        <h2 className="font-display text-base font-bold uppercase tracking-[0.12em] text-slate-100 md:text-lg">Ajustes · HotForex AI Trading</h2>
        <p className="text-[12px] text-slate-500">Cuenta real de HFM (vía MetaApi) y cambio de modo, agente de noticias y trading por noticias, cuenta paper. La clave de acceso, la IA y Telegram son compartidos con el bot de criptomonedas. La estrategia y el riesgo se configuran desde el panel principal.</p>
      </div>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <HfmSection config={config} onSave={save} onRefresh={load} />
        <LiveModeSection config={config} refresh={() => { load(); refresh?.(); }} labels={HFM_LIVE_LABELS} />
        <FxNewsSection config={config} onSave={save} />
        <SecuritySection />
        <AiSection config={config} onSave={save} />
        <TelegramSection config={config} onSave={save} showWeekly={false} />
        <AccountSection account={account} refresh={refresh} />
      </div>
    </div>
  );
}
