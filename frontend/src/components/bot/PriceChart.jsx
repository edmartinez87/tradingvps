import { useEffect, useRef, useState } from "react";
import {
  createChart, CandlestickSeries, LineSeries, HistogramSeries, createSeriesMarkers, ColorType, CrosshairMode, LineStyle,
} from "lightweight-charts";
import { CandlestickChart } from "lucide-react";
import { Panel } from "./Panel";
import { http, fmtPrice } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";

const TFS = ["1m", "5m", "15m", "1h", "4h"];
const lineOpts = (color, width = 1) => ({ color, lineWidth: width, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });

function useChart(ref) {
  const api = useRef(null);
  useEffect(() => {
    const chart = createChart(ref.current, {
      autoSize: true,
      localization: { locale: "es-ES" },
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#94A3B8", fontFamily: "IBM Plex Mono, monospace", fontSize: 11, panes: { separatorColor: "#1E293B" } },
      grid: { vertLines: { color: "rgba(30,41,59,0.45)" }, horzLines: { color: "rgba(30,41,59,0.45)" } },
      rightPriceScale: { borderColor: "#1E293B" },
      timeScale: { borderColor: "#1E293B", timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });
    const candles = chart.addSeries(CandlestickSeries, { upColor: "#10B981", downColor: "#EF4444", borderVisible: false, wickUpColor: "#10B981", wickDownColor: "#EF4444" });
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const e9 = chart.addSeries(LineSeries, lineOpts("#F7A600"));
    const e21 = chart.addSeries(LineSeries, lineOpts("#38BDF8"));
    const e200 = chart.addSeries(LineSeries, lineOpts("#CBD5E1", 2));
    const rsi = chart.addSeries(LineSeries, { ...lineOpts("#F472B6"), lastValueVisible: true }, 1);
    rsi.createPriceLine({ price: 70, color: "rgba(239,68,68,0.45)", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
    rsi.createPriceLine({ price: 30, color: "rgba(16,185,129,0.45)", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
    try { chart.panes()[1].setHeight(90); } catch (e) { /* pane api optional */ }
    const markers = createSeriesMarkers(candles, []);
    api.current = { chart, candles, vol, e9, e21, e200, rsi, markers, lines: [] };
    return () => { chart.remove(); api.current = null; };
  }, [ref]);
  return api;
}

export default function PriceChart({ symbol, defaultTf }) {
  const [tf, setTf] = useState(defaultTf);
  const ref = useRef(null);
  const api = useChart(ref);
  const fitted = useRef("");
  const { data } = usePolling(() => http.get("/klines", { params: { symbol, tf } }).then((r) => r.data), 10000, [symbol, tf]);

  useEffect(() => setTf(defaultTf), [defaultTf]);

  useEffect(() => {
    const a = api.current;
    if (!a || !data || data.symbol !== symbol || data.tf !== tf) return;
    a.candles.setData(data.candles);
    a.vol.setData(data.volume);
    a.e9.setData(data.ema9);
    a.e21.setData(data.ema21);
    a.e200.setData(data.ema200);
    a.rsi.setData(data.rsi);
    a.markers.setMarkers(data.markers);
    a.lines.forEach((l) => a.candles.removePriceLine(l));
    a.lines = data.lines.map((l) => a.candles.createPriceLine({ price: l.price, color: l.color, title: l.title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true }));
    const key = `${symbol}-${tf}`;
    if (fitted.current !== key) {
      const n = data.candles.length;
      a.chart.timeScale().setVisibleLogicalRange({ from: n - 120, to: n + 4 });
      fitted.current = key;
    }
  }, [data, symbol, tf, api]);

  const last = data?.candles?.[data.candles.length - 1];
  return (
    <Panel testId="price-chart-panel" title={`${symbol} · Perpetuo`} icon={CandlestickChart} className="lg:col-span-6" bodyClass="flex flex-col" delay={120}
      actions={
        <div className="flex items-center gap-1 rounded-sm border border-[#1E293B] p-0.5">
          {TFS.map((t) => (
            <button key={t} data-testid={`chart-tf-${t}`} onClick={() => setTf(t)}
              className={`rounded-sm px-2 py-0.5 font-mono text-[11px] transition-colors ${t === tf ? "bg-amber-500 text-[#07090E]" : "text-slate-400 hover:text-slate-100"}`}>
              {t}
            </button>
          ))}
        </div>
      }>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 pt-3 font-mono text-[11px]">
        <span data-testid="chart-last-price" className="text-base font-semibold text-slate-50">{fmtPrice(last?.close)}</span>
        <span className="text-amber-400">EMA 9</span>
        <span className="text-sky-400">EMA 21</span>
        <span className="text-slate-300">EMA 200</span>
        <span className="text-pink-400">RSI 14</span>
      </div>
      <div ref={ref} data-testid="price-chart" className="h-[470px] w-full" />
    </Panel>
  );
}
