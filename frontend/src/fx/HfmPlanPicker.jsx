import { Check, Loader2, RefreshCcwDot, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const usd = (v, d = 3) => `$${Number(v).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: d })}`;

export function HfmPlanPicker({ plans = [], common, value, onChange, currentPlan, disabled }) {
  return (
    <div data-testid="hfm-plan-picker">
      <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-slate-500">Tipo de cuenta MetaApi · coste (pay as you go, USD sin IVA)</p>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {plans.map((p) => {
          const active = value === p.key;
          return (
            <button key={p.key} type="button" data-testid={`hfm-plan-${p.key}`} onClick={() => onChange(p.key)} disabled={disabled} aria-pressed={active}
              className={`relative rounded-sm border p-3 text-left transition-colors ${active ? "border-amber-400/70 bg-amber-500/10" : "border-[#1E293B] bg-[#07090E] hover:border-slate-600"} disabled:opacity-50`}>
              <div className="flex items-start justify-between gap-2">
                <span className="font-display text-[12.5px] font-semibold text-slate-100">{p.label}</span>
                <span className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border ${active ? "border-amber-400 bg-amber-400 text-[#07090E]" : "border-slate-600"}`}>{active && <Check className="h-3 w-3" strokeWidth={3} />}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {p.recommended && <span className="inline-flex items-center gap-1 rounded-sm border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-emerald-300"><Star className="h-2.5 w-2.5" /> Recomendada</span>}
                {currentPlan === p.key && <span data-testid="hfm-plan-current-badge" className="rounded-sm border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wider text-sky-300">Actual en MetaApi</span>}
              </div>
              <p className="num mt-2 font-mono text-[11px] text-slate-200">{usd(p.hour_usd, 4)}/h <span className="text-slate-500">·</span> ≈ {usd(p.month_usd, 2)}/mes 24/7 <span className="text-slate-500">·</span> {usd(p.deploy_usd, 3)} por despliegue</p>
              <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">{p.note}</p>
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">
        Común a todas: {usd(common?.account_month_usd ?? 2.1, 2)}/mes por cuenta única y {usd(common?.undeployed_hour_usd ?? 0.00105, 5)}/h si la cuenta está sin desplegar. Para demo y para real la opción
        más barata y estable es <span className="text-slate-300">Cloud G2</span>. El tipo no se puede cambiar en una cuenta ya creada: si lo cambias, usa «Recrear con el nuevo tipo».
      </p>
    </div>
  );
}

export function HfmRecreateNotice({ currentLabel, wantedLabel, busy, onRecreate }) {
  return (
    <div data-testid="hfm-plan-mismatch" className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-amber-500/40 bg-amber-500/10 p-3">
      <p className="text-[12px] leading-relaxed text-amber-200">
        La cuenta existe en MetaApi como <b>{currentLabel}</b> y has elegido <b>{wantedLabel}</b>. MetaApi no permite cambiar el tipo: hay que borrarla y crearla de nuevo
        (la cuota de $2,10 no se cobra dos veces en el mismo mes para el mismo login).
      </p>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button data-testid="hfm-recreate-button" variant="outline" disabled={busy} title="Requiere el bot detenido"
            className="h-8 border-amber-500/50 bg-transparent font-mono text-[11px] uppercase tracking-wider text-amber-200 hover:bg-amber-500/15">
            {busy ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCcwDot className="mr-1.5 h-3.5 w-3.5" />} Recrear con el nuevo tipo
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent data-testid="hfm-recreate-dialog" className="border-amber-500/30 bg-[#0D111A]">
          <AlertDialogHeader>
            <AlertDialogTitle className="font-display text-amber-200">Recrear la cuenta en MetaApi como {wantedLabel}</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2 text-slate-400">
              <span className="block">1. Se borra la cuenta actual ({currentLabel}) de MetaApi: deja de facturarse por hora.</span>
              <span className="block">2. Se crea de nuevo con el mismo login/servidor del bróker como {wantedLabel} y se despliega (1–3 minutos en conectar).</span>
              <span className="block">3. Después pulsa «Probar conexión» y «Comprobar símbolos» para verificarla otra vez. Las operaciones abiertas en el bróker no se tocan.</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="hfm-recreate-cancel" className="border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider text-slate-300 hover:bg-[#111827]">Cancelar</AlertDialogCancel>
            <AlertDialogAction data-testid="hfm-recreate-confirm" onClick={onRecreate} className="bg-amber-500 font-mono text-[11px] font-bold uppercase tracking-wider text-[#07090E] hover:bg-amber-400">Recrear ahora</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
