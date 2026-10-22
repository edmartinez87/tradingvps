import { useState } from "react";
import { Wallet, Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Panel } from "../Panel";
import { http, errMsg, fmtUsd, fmtSignedUsd, pnlClass } from "@/lib/api";
import { Field, INPUT } from "./SecuritySection";
import CashFlowsCard from "./CashFlowsCard";

export default function AccountSection({ account, refresh, currency = "USDT" }) {
  const [initial, setInitial] = useState(account.initial_balance);
  const [loading, setLoading] = useState(false);
  const live = account.mode === "REAL";

  const reset = async () => {
    setLoading(true);
    try {
      await http.post("/account/reset", { initial_balance: Number(initial) });
      toast.success(`Cuenta paper reiniciada a ${fmtUsd(Number(initial), 0)}`);
      refresh?.();
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel testId="account-section" title={live ? "Cuenta y aportes" : "Cuenta paper"} icon={Wallet} bodyClass="p-4 space-y-3">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-4">
        {[["Capital inicial", fmtUsd(account.initial_balance, 0), null, "account-initial"], ["Aportes netos", fmtSignedUsd(account.net_deposits ?? 0), account.net_deposits ?? 0, "account-net-deposits"],
          ["Equidad", fmtUsd(account.equity), null, "account-equity"], ["Operaciones", account.total_trades, null, "account-trades"]].map(([l, v, tone, tid]) => (
          <div key={l} data-testid={tid} className="bg-[#0D111A] px-3 py-2.5"><p className="font-mono text-[9px] uppercase tracking-[0.16em] text-slate-500">{l}</p><p className={`num mt-1 text-sm font-semibold ${tone != null && tone !== 0 ? pnlClass(tone) : "text-slate-100"}`}>{v}</p></div>
        ))}
      </div>
      <p data-testid="account-return-note" className="text-[11px] text-slate-500">
        Retorno total <span className={pnlClass(account.total_return_pct)}>{account.total_return_pct > 0 ? "+" : ""}{Number(account.total_return_pct).toFixed(2)}%</span> = PnL <span className={pnlClass(account.total_pnl ?? 0)}>{fmtSignedUsd(account.total_pnl ?? account.equity - account.initial_balance)}</span> sobre el capital aportado {fmtUsd(account.capital ?? account.initial_balance)} (inicial + aportes netos). Los depósitos y retiros no cuentan como ganancia ni pérdida.
      </p>
      <CashFlowsCard account={account} refresh={refresh} currency={currency} />
      {!live && (
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[160px] flex-1">
          <Field label={`Nuevo capital inicial (${currency})`} hint="El plan de crecimiento usa este valor como punto de partida.">
            <Input data-testid="account-initial-input" type="number" min={10} step={50} value={initial} onChange={(e) => setInitial(e.target.value)} className={INPUT} />
          </Field>
        </div>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button data-testid="account-reset-button" variant="outline" disabled={loading || !(Number(initial) >= 10)} className="h-9 border-rose-500/40 bg-transparent font-mono text-[11px] uppercase tracking-wider text-rose-300 hover:bg-rose-500/10">
              {loading ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="mr-1.5 h-3.5 w-3.5" />} Reiniciar con este capital
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent data-testid="account-reset-dialog" className="border-[#1E293B] bg-[#0D111A]">
            <AlertDialogHeader>
              <AlertDialogTitle className="font-display">¿Reiniciar la cuenta paper con {fmtUsd(Number(initial) || 0, 0)}?</AlertDialogTitle>
              <AlertDialogDescription>Se borran posiciones, historial, señales y curva de equidad. El chequeo del plan vuelve a empezar desde cero.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel data-testid="account-reset-cancel">Cancelar</AlertDialogCancel>
              <AlertDialogAction data-testid="account-reset-confirm" onClick={reset} className="bg-rose-500 text-white hover:bg-rose-600">Reiniciar</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      )}
    </Panel>
  );
}
