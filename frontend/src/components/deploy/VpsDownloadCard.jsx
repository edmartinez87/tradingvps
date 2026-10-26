import { useEffect, useState } from "react";
import { HardDriveDownload, Loader2, Package, CheckCircle2, XCircle, GitCommitHorizontal } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api, errMsg, fmtDateTime } from "@/lib/api";

const fileNameFrom = (r, fallback) => {
  const m = /filename="?([^";]+)"?/.exec(r.headers?.["content-disposition"] || "");
  return m ? m[1] : fallback;
};

export function VpsDownloadCard() {
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get(`/deploy/info`).then((r) => setInfo(r.data)).catch((e) => setErr(errMsg(e)));
  }, []);

  const download = async () => {
    setBusy(true);
    try {
      const r = await api.get(`/deploy/package`, { responseType: "blob", timeout: 300000 });
      const name = fileNameFrom(r, info?.package || "ai-trader.zip");
      const url = URL.createObjectURL(r.data);
      const a = Object.assign(document.createElement("a"), { href: url, download: name });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast.success(`Paquete descargado · ${name} · ${(r.data.size / 1048576).toFixed(1)} MB`);
    } catch (e) {
      toast.error(e?.response?.data instanceof Blob ? "No se pudo generar el paquete" : errMsg(e));
    } finally { setBusy(false); }
  };

  return (
    <section data-testid="vps-download-card" className="relative overflow-hidden rounded-md border border-emerald-500/30 bg-[#0D111A] p-6 md:p-8">
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-emerald-500/10 blur-3xl" />
      <div className="relative grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-400">Paso 0 · descarga</p>
          <h2 className="font-display mt-2 text-xl font-bold leading-snug text-slate-50 md:text-2xl">Descarga la última versión completa de la app</h2>
          <p className="mt-3 max-w-2xl text-[13px] leading-relaxed text-slate-300">
            Un único archivo .zip con los dos bots (Bybit y HotForex), el panel web y los scripts de instalación. Sigue los pasos de abajo y en unos
            15 minutos tendrás tu propia copia funcionando 24/7 en tu servidor, independiente de este panel.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button data-testid="vps-download-button" onClick={download} disabled={busy || !info?.available}
              className="h-10 bg-emerald-500 px-5 font-mono text-[12px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-emerald-400 disabled:opacity-60">
              {busy ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Generando paquete…</> : <><HardDriveDownload className="mr-2 h-4 w-4" /> Descargar ZIP</>}
            </Button>
            {info?.available && (
              <div data-testid="vps-package-meta" className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-slate-400">
                <span className="inline-flex items-center gap-1.5"><GitCommitHorizontal className="h-3.5 w-3.5 text-emerald-400" /> versión <b className="text-slate-200" data-testid="vps-version">{info.version}</b></span>
                {info.commit_date && <span>· {fmtDateTime(info.commit_date)}</span>}
                <span>· {info.files} archivos · ≈{info.source_mb} MB sin comprimir</span>
              </div>
            )}
            {info && !info.available && <p data-testid="vps-unavailable" className="text-[12px] text-rose-300">{info.reason}</p>}
            {err && <p className="text-[12px] text-rose-300">{err}</p>}
            {!info && !err && <span className="inline-flex items-center gap-2 font-mono text-[11px] text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Comprobando la versión…</span>}
          </div>
          {info?.package && <p className="mt-2 font-mono text-[10.5px] text-slate-500">Nombre del archivo: <span className="text-slate-300">{info.package}</span></p>}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <div className="rounded-sm border border-[#1E293B] bg-[#07090E] p-4">
            <p className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-emerald-400"><CheckCircle2 className="h-3.5 w-3.5" /> Incluye</p>
            <ul className="mt-2 space-y-1 text-[12px] text-slate-300">
              {["backend/ · motores de trading, IA, riesgo, API", "frontend/ · panel web completo", "deploy/ · instalador, Docker, crons, copias, guía INSTALACION.md", "scripts/ · utilidades y simuladores para pruebas"].map((t) => (
                <li key={t} className="flex gap-2"><Package className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-500" />{t}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-sm border border-[#1E293B] bg-[#07090E] p-4">
            <p className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-rose-400"><XCircle className="h-3.5 w-3.5" /> No incluye (por seguridad)</p>
            <ul className="mt-2 space-y-1 text-[12px] text-slate-400">
              {(info?.excluded || ["archivos .env y backend.env (secretos)", "base de datos y copias de seguridad", "node_modules y builds", "tests y cachés"]).map((t) => <li key={t} className="flex gap-2"><span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-rose-400" />{t}</li>)}
            </ul>
            <p className="mt-2 text-[11px] text-slate-500">Tus datos se pueden llevar aparte con una copia de seguridad (paso 9).</p>
          </div>
        </div>
      </div>
    </section>
  );
}
