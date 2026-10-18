import { useEffect, useState } from "react";
import "@/App.css";
import { Toaster, toast } from "sonner";
import { Layers, Loader2 } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { http, errMsg } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import Header from "@/components/bot/Header";
import KpiStrip from "@/components/bot/KpiStrip";
import Watchlist from "@/components/bot/Watchlist";
import PriceChart from "@/components/bot/PriceChart";
import BotPanel from "@/components/bot/BotPanel";
import PositionsTable from "@/components/bot/PositionsTable";
import TradeHistory from "@/components/bot/TradeHistory";
import Backtest from "@/components/bot/Backtest";
import Performance from "@/components/bot/Performance";
import GrowthPlan from "@/components/bot/GrowthPlan";
import AiSignals from "@/components/bot/AiSignals";
import SettingsPanel from "@/components/bot/SettingsPanel";
import Terminal from "@/components/bot/Terminal";
import { Panel } from "@/components/bot/Panel";

const TAB_CLS = "rounded-sm px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider data-[state=active]:bg-amber-500 data-[state=active]:text-[#07090E]";

function Dashboard() {
  const [meta, setMeta] = useState(null);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [busy, setBusy] = useState(false);
  const { data, refresh } = usePolling(() => http.get("/dashboard").then((r) => r.data), 3000);

  useEffect(() => {
    document.title = "Bybit AI Trader · Panel de control";
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
      <div data-testid="dashboard-loading" className="flex min-h-screen items-center justify-center gap-3 font-mono text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin text-amber-400" /> Conectando con el motor de trading...
      </div>
    );
  }

  const toggleBot = async () => {
    setBusy(true);
    const running = data.status.running;
    await act(() => http.post(running ? "/bot/stop" : "/bot/start"), running ? "Bot detenido" : "Bot iniciado · operando 24/7");
    setBusy(false);
  };

  return (
    <div data-testid="dashboard" className="app-bg grain min-h-screen">
      <Header status={data.status} busy={busy} onToggle={toggleBot}
        onScan={() => act(() => http.post("/bot/scan"), "Escaneo solicitado")}
        onReset={() => act(() => http.post("/account/reset"), "Cuenta paper reiniciada")} />
      <main className="mx-auto max-w-[1920px] space-y-4 p-4 md:p-6">
        <KpiStrip account={data.account} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Watchlist items={data.watchlist} selected={symbol} onSelect={setSymbol} />
          <PriceChart symbol={symbol} defaultTf={data.settings.timeframe} />
          <BotPanel settings={data.settings} meta={meta} account={data.account} equity={data.equity} />
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:items-start">
          <Panel testId="operations-panel" className="lg:col-span-8" delay={220}>
            <Tabs defaultValue="positions" className="flex h-full flex-col">
              <div className="flex items-center gap-3 border-b border-[#1E293B] px-4 py-2.5">
                <Layers className="h-4 w-4 text-amber-400" />
                <TabsList className="h-auto gap-1 bg-transparent p-0">
                  <TabsTrigger data-testid="tab-positions" value="positions" className={TAB_CLS}>Posiciones ({data.positions.length})</TabsTrigger>
                  <TabsTrigger data-testid="tab-history" value="history" className={TAB_CLS}>Historial</TabsTrigger>
                  <TabsTrigger data-testid="tab-backtest" value="backtest" className={TAB_CLS}>Backtest</TabsTrigger>
                  <TabsTrigger data-testid="tab-performance" value="performance" className={TAB_CLS}>Rendimiento</TabsTrigger>
                  <TabsTrigger data-testid="tab-plan" value="plan" className={TAB_CLS}>Plan de crecimiento</TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="positions" className="mt-0">
                <PositionsTable positions={data.positions} onClose={(id) => act(() => http.post(`/positions/${id}/close`), "Posición cerrada")} />
              </TabsContent>
              <TabsContent value="history" className="mt-0"><TradeHistory trades={data.trades} /></TabsContent>
              <TabsContent value="backtest" className="mt-0"><Backtest meta={meta} settings={data.settings} /></TabsContent>
              <TabsContent value="performance" className="mt-0"><Performance tradeCount={data.account.total_trades} /></TabsContent>
              <TabsContent value="plan" className="mt-0"><GrowthPlan account={data.account} /></TabsContent>
            </Tabs>
          </Panel>
          <AiSignals signals={data.signals} />
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <SettingsPanel settings={data.settings} meta={meta} onSave={(body) => act(() => http.put("/settings", body), "Configuración guardada")} />
          <Terminal logs={data.logs} onClear={() => act(() => http.delete("/logs"))} />
        </div>
        <p className="pb-4 pt-2 font-mono text-[10px] uppercase tracking-wider text-slate-600">
          Simulación con precios reales · No es asesoría financiera · El trading con apalancamiento implica alto riesgo
        </p>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <>
      <Dashboard />
      <Toaster theme="dark" position="bottom-right" toastOptions={{ style: { background: "#0D111A", border: "1px solid #1E293B", fontFamily: "Outfit" } }} />
    </>
  );
}
