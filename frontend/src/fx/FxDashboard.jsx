import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Layers, Loader2, Landmark } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { http, errMsg, setApiBase } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import Header from "@/components/bot/Header";
import KpiStrip from "@/components/bot/KpiStrip";
import Watchlist from "@/components/bot/Watchlist";
import PriceChart from "@/components/bot/PriceChart";
import BotPanel from "@/components/bot/BotPanel";
import PositionsTable from "@/components/bot/PositionsTable";
import TradeHistory from "@/components/bot/TradeHistory";
import Performance from "@/components/bot/Performance";
import AiSignals from "@/components/bot/AiSignals";
import SettingsPanel from "@/components/bot/SettingsPanel";
import Terminal from "@/components/bot/Terminal";
import { Panel } from "@/components/bot/Panel";
import SessionsStrip from "./SessionsStrip";
import FxNewsPanel from "./FxNewsPanel";
import FxAdminSettings from "./FxAdminSettings";

const TAB_CLS = "rounded-sm px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider data-[state=active]:bg-amber-500 data-[state=active]:text-[#07090E]";
const FX_TFS = ["5m", "15m", "1h", "4h"];
export const FX_BRAND = {
  title: <>HotForex <span className="text-sky-400">AI</span> Trading</>,
  subtitle: "Forex · Metales · Claude Sonnet",
  icon: Landmark,
  liveLabel: (status) => `Modo REAL · HFM ${status.env}`,
  dataLabel: () => "Datos: Yahoo Finance",
  dataTooltip: () => "Precios y velas de Yahoo Finance (sin API key): pares spot y futuros de oro (GC=F) y plata (SI=F) que replican el spot. Cuando vincules tu cuenta HFM vía MetaApi, el modo real usará los precios y símbolos de tu propio bróker.",
  resetHint: "Se borrarán posiciones, historial, señales, operaciones de noticias y curva de equidad. El balance vuelve al capital inicial configurado (por defecto $500).",
};
const EXTRA_TOGGLES = [{ k: "close_before_weekend", label: "Cerrar antes del fin de semana", hint: "Cierra todo 30 min antes del cierre del viernes (evita gaps del domingo)" }];

export default function FxDashboard({ onLogout }) {
  setApiBase("fx");
  const nav = useNavigate();
  const [meta, setMeta] = useState(null);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState("panel");
  const { data, refresh } = usePolling(() => http.get("/dashboard").then((r) => r.data), 4000);

  useEffect(() => {
    document.title = "HotForex AI Trading · Panel de control";
    http.get("/meta").then((r) => setMeta(r.data)).catch(() => toast.error("No se pudo cargar la configuración"));
  }, []);

  const symbols = data?.settings.symbols;
  useEffect(() => {
    if (symbols?.length && !symbols.includes(symbol)) setSymbol(symbols[0]);
  }, [symbols, symbol]);

  const act = async (fn, okMsg) => {
    try {
      await fn();
      if (okMsg) toast.success(okMsg);
      await refresh();
      return true;
    } catch (e) {
      toast.error(errMsg(e));
      return false;
    }
  };

  if (!data) {
    return (
      <div data-testid="fx-dashboard-loading" className="flex min-h-screen items-center justify-center gap-3 font-mono text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin text-sky-400" /> Conectando con el motor HotForex...
      </div>
    );
  }

  const toggleBot = async () => {
    setBusy(true);
    const running = data.status.running;
    await act(() => http.post(running ? "/bot/stop" : "/bot/start"), running ? "Bot detenido" : "Bot iniciado · operando en horario forex");
    setBusy(false);
  };
  const newsAlert = data.news?.risk === "ALTO" || data.news?.blocked || data.news?.critical?.length > 0;

  return (
    <div data-testid="fx-dashboard" className="app-bg grain min-h-screen">
      <Header status={data.status} busy={busy} onToggle={toggleBot} view={view} onLogout={onLogout} brand={FX_BRAND} onSwitchBot={() => nav("/")}
        onSettings={() => setView((v) => (v === "settings" ? "panel" : "settings"))}
        onScan={() => act(() => http.post("/bot/scan"), "Escaneo solicitado")}
        onReset={() => act(() => http.post("/account/reset", {}), "Cuenta paper reiniciada")} />
      {view === "settings" ? (
        <main className="mx-auto max-w-[1920px] p-4 md:p-6"><FxAdminSettings account={data.account} refresh={refresh} /></main>
      ) : (
      <main className="mx-auto max-w-[1920px] space-y-4 p-4 md:p-6">
        {data.status.exchange_error && (
          <div data-testid="fx-exchange-error-banner" className="rounded-md border border-rose-500/40 bg-rose-500/10 px-4 py-2 font-mono text-[11px] text-rose-200">
            Yahoo Finance sin respuesta: {data.status.exchange_error} · mostrando los últimos datos locales
          </div>
        )}
        <SessionsStrip hours={data.status.market_hours} />
        <KpiStrip account={data.account} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Watchlist items={data.watchlist} selected={symbol} onSelect={setSymbol} />
          <PriceChart symbol={symbol} defaultTf={data.settings.timeframe} kind={meta?.symbol_info?.[symbol]?.name || "Forex"} tfs={FX_TFS} />
          <BotPanel settings={data.settings} meta={meta} account={data.account} equity={data.equity} profileActive={null} />
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:items-start">
          <Panel testId="fx-operations-panel" className="lg:col-span-8" delay={220}>
            <Tabs defaultValue="positions" className="flex h-full flex-col">
              <div className="flex items-center gap-3 border-b border-[#1E293B] px-4 py-2.5">
                <Layers className="h-4 w-4 text-amber-400" />
                <TabsList className="h-auto gap-1 bg-transparent p-0">
                  <TabsTrigger data-testid="fx-tab-positions" value="positions" className={TAB_CLS}>Posiciones ({data.positions.length})</TabsTrigger>
                  <TabsTrigger data-testid="fx-tab-history" value="history" className={TAB_CLS}>Historial</TabsTrigger>
                  <TabsTrigger data-testid="fx-tab-performance" value="performance" className={TAB_CLS}>Rendimiento</TabsTrigger>
                  <TabsTrigger data-testid="fx-tab-news" value="news" className={`${TAB_CLS} relative`}>
                    Noticias y agenda
                    {newsAlert && <span data-testid="fx-tab-news-alert" className="pulse-dot absolute -right-1 -top-1 bg-rose-400" />}
                  </TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="positions" className="mt-0">
                <PositionsTable positions={data.positions} onClose={(id) => act(() => http.post(`/positions/${id}/close`), "Posición cerrada")}
                  onCloseAll={() => act(() => http.post("/positions/close-all"), "Cierre de emergencia ejecutado")} />
              </TabsContent>
              <TabsContent value="history" className="mt-0"><TradeHistory trades={data.trades} /></TabsContent>
              <TabsContent value="performance" className="mt-0">
                <Performance tradeCount={data.account.total_trades} settings={data.settings} onSave={(body) => act(() => http.put("/settings", body), "Configuración actualizada")} />
              </TabsContent>
              <TabsContent value="news" className="mt-0"><FxNewsPanel summary={data.news} symbols={data.settings.symbols} currencyNames={meta?.currency_names} /></TabsContent>
            </Tabs>
          </Panel>
          <AiSignals signals={data.signals} />
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <SettingsPanel settings={data.settings} meta={meta} profileActive={null} leverageMax={500} extraToggles={EXTRA_TOGGLES}
            onSave={(body) => act(() => http.put("/settings", body), "Configuración guardada")} onProfile={async () => false} />
          <Terminal logs={data.logs} onClear={() => act(() => http.delete("/logs"))} />
        </div>
        <p className="pb-4 pt-2 font-mono text-[10px] uppercase tracking-wider text-slate-600">
          Simulación con precios reales de Yahoo Finance · Lotes y pips según especificaciones HFM · No es asesoría financiera · El apalancamiento implica alto riesgo
        </p>
      </main>
      )}
    </div>
  );
}
