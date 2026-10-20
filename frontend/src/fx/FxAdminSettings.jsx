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
        <p className="text-[12px] text-slate-500">Cuenta real de HFM (vía MetaApi), agente de noticias y trading por noticias, cuenta paper. La clave de acceso, la IA y Telegram son compartidos con el bot de criptomonedas. La estrategia y el riesgo se configuran desde el panel principal.</p>
      </div>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <HfmSection config={config} onSave={save} onRefresh={load} />
        <FxNewsSection config={config} onSave={save} />
        <SecuritySection />
        <AiSection config={config} onSave={save} />
        <TelegramSection config={config} onSave={save} showWeekly={false} />
        <AccountSection account={account} refresh={refresh} />
      </div>
    </div>
  );
}
