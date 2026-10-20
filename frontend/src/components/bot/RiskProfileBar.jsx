import { useEffect, useRef, useState } from "react";
import { Gauge, Loader2, AlertTriangle, Flame } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { MODE_LABELS } from "@/lib/api";

const TONE = [
  { text: "text-emerald-300", border: "border-emerald-500/40", bg: "bg-emerald-500/10", bar: "#10B981" },
  { text: "text-lime-300", border: "border-lime-500/40", bg: "bg-lime-500/10", bar: "#84CC16" },
  { text: "text-amber-300", border: "border-amber-500/40", bg: "bg-amber-500/10", bar: "#F59E0B" },
  { text: "text-orange-300", border: "border-orange-500/40", bg: "bg-orange-500/10", bar: "#F97316" },
  { text: "text-rose-300", border: "border-rose-500/40", bg: "bg-rose-500/10", bar: "#F43F5E" },
];

const Chip = ({ label, value, testId }) => (
  <div data-testid={testId} className="rounded-sm border border-[#1E293B] bg-[#07090E]/70 px-2 py-1.5">
    <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-slate-500">{label}</p>
    <p className="num mt-0.5 text-[12px] font-semibold text-slate-100">{value}</p>
  </div>
);

export default function RiskProfileBar({ profiles = [], active, selected = 0, onApply }) {
  const [level, setLevel] = useState(active ?? selected ?? 0);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const applying = useRef(false);
  useEffect(() => { setLevel(active ?? selected ?? 0); }, [active, selected]);
  if (!profiles.length) return null;

  const p = profiles[level];
  const s = p.settings;
  const tone = TONE[level];
  const custom = active == null;
  const dirty = level !== active;

  const apply = async () => {
    applying.current = true;
    setBusy(true);
    const ok = await onApply(level);
    setBusy(false);
    setConfirm(false);
    applying.current = false;
    if (!ok) setLevel(active ?? selected ?? 0);
  };
  const request = () => (level >= 3 ? setConfirm(true) : apply());

  return (
    <div data-testid="risk-profile-bar" className={`rounded-md border ${tone.border} ${tone.bg} p-3.5 transition-colors duration-300`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
            <Gauge className="h-3.5 w-3.5" /> Perfil de riesgo
            {custom && <span data-testid="risk-profile-custom-badge" className="ml-1 rounded-sm border border-slate-500/40 px-1.5 py-px text-[9px] text-slate-300">Personalizado</span>}
          </p>
          <p data-testid="risk-profile-name" className={`font-display mt-1 text-lg font-bold ${tone.text}`}>
            {level}. {p.name} <span className="font-mono text-[11px] font-normal text-slate-400">· {p.activity}</span>
          </p>
        </div>
        <Button data-testid="risk-profile-apply-button" size="sm" onClick={request} disabled={!dirty || busy}
          className={`h-8 font-mono text-[10px] font-bold uppercase tracking-wider text-[#07090E] disabled:opacity-40 ${level >= 3 ? "bg-rose-400 hover:bg-rose-300" : "bg-amber-500 hover:bg-amber-400"}`}>
          {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
          {custom && !dirty ? "Aplicar nivel" : dirty ? `Aplicar nivel ${level}` : "Nivel activo"}
        </Button>
      </div>

      <div className="mt-3 px-1">
        <Slider data-testid="risk-profile-slider" value={[level]} min={0} max={4} step={1} onValueChange={([v]) => setLevel(v)}
          className="[&_[role=slider]]:h-5 [&_[role=slider]]:w-5 [&_[role=slider]]:border-2 [&_[role=slider]]:bg-[#0D111A]" />
        <div className="mt-2 flex justify-between font-mono text-[9px] uppercase tracking-wider">
          {profiles.map((x) => (
            <button key={x.level} data-testid={`risk-profile-step-${x.level}`} onClick={() => setLevel(x.level)}
              className={`transition-colors ${x.level === level ? TONE[x.level].text : "text-slate-400 hover:text-slate-200"}`}>
              {x.name}
            </button>
          ))}
        </div>
      </div>

      <p data-testid="risk-profile-tagline" className="mt-3 text-[12px] leading-relaxed text-slate-300">{p.tagline}</p>
      <div className="mt-3 grid grid-cols-3 gap-1.5 sm:grid-cols-5">
        <Chip label="Pares" value={s.symbols.length} testId="risk-profile-chip-symbols" />
        <Chip label="Velas" value={s.timeframe} testId="risk-profile-chip-tf" />
        <Chip label="Criterios" value={MODE_LABELS[s.signal_mode]} testId="risk-profile-chip-mode" />
        <Chip label="Filtro TF sup." value={s.htf_filter ? "Sí" : "No"} testId="risk-profile-chip-htf" />
        <Chip label="IA" value={s.ai_enabled ? `≥${s.ai_min_confidence}%` : "Apagada"} testId="risk-profile-chip-ai" />
        <Chip label="Riesgo/op" value={`${s.risk_per_trade}%`} testId="risk-profile-chip-risk" />
        <Chip label="Máx. pos." value={s.max_positions} testId="risk-profile-chip-pos" />
        <Chip label="Apalanc." value={`${s.leverage}x`} testId="risk-profile-chip-lev" />
        <Chip label="Límite día" value={`-${s.daily_loss_limit}%`} testId="risk-profile-chip-dll" />
        <Chip label="Estrategias" value={5 - s.disabled_strategies.length} testId="risk-profile-chip-strats" />
      </div>
      {p.warning && (
        <p data-testid="risk-profile-warning" className={`mt-3 flex gap-2 rounded-sm border ${tone.border} px-3 py-2 text-[11.5px] leading-snug ${tone.text}`}>
          {level >= 4 ? <Flame className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
          {p.warning}
        </p>
      )}

      <AlertDialog open={confirm} onOpenChange={(o) => { setConfirm(o); if (!o && !applying.current) setLevel(active ?? selected ?? 0); }}>
        <AlertDialogContent data-testid="risk-profile-dialog" className="border-rose-500/30 bg-[#0D111A]">
          <AlertDialogHeader>
            <AlertDialogTitle className="font-display text-rose-300">Activar perfil {p.name}</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2 text-slate-400">
              <span className="block">{p.warning}</span>
              <span className="block">El bot abrirá posiciones mucho más a menudo. Puede <b className="text-rose-300">quemar la cuenta más rápido</b> o ganar más rápido; no hay garantías. Puedes volver al nivel Conservador en cualquier momento.</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="risk-profile-cancel">Cancelar</AlertDialogCancel>
            <AlertDialogAction data-testid="risk-profile-confirm-button" onClick={apply} disabled={busy} className="bg-rose-500 text-white hover:bg-rose-400">
              Entiendo el riesgo, activar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
