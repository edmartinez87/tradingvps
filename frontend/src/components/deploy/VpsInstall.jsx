import * as Icons from "lucide-react";
import { Server, ArrowLeft, TerminalSquare, LifeBuoy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { VpsDownloadCard } from "./VpsDownloadCard";
import { VpsSteps } from "./VpsSteps";
import { CodeBlock } from "./CodeBlock";
import { REQUIREMENTS, COMMANDS, TROUBLE } from "./vpsContent";

const Icon = ({ name, className }) => { const C = Icons[name] || Icons.Circle; return <C className={className} />; };

function Requirements() {
  return (
    <section data-testid="vps-requirements" className="space-y-3">
      <div>
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-400">Antes de empezar</p>
        <h2 className="font-display mt-1 text-lg font-bold text-slate-50">Qué necesitas</h2>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {REQUIREMENTS.map((r, i) => (
          <article key={r.title} data-testid={`vps-req-${i}`} className="rise rounded-md border border-[#1E293B] bg-[#0D111A] p-4" style={{ animationDelay: `${i * 40}ms` }}>
            <div className="flex items-center gap-2"><span className="inline-flex h-7 w-7 items-center justify-center rounded-sm border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"><Icon name={r.icon} className="h-3.5 w-3.5" /></span><h3 className="font-display text-[13px] font-semibold text-slate-100">{r.title}</h3></div>
            <p className="mt-2 text-[12px] leading-relaxed text-slate-400">{r.text}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function Commands() {
  return (
    <section data-testid="vps-commands" className="rounded-md border border-[#1E293B] bg-[#0D111A] p-5">
      <h2 className="flex items-center gap-2 font-display text-[14px] font-semibold text-slate-100"><TerminalSquare className="h-4 w-4 text-emerald-400" /> Comandos útiles · dentro de <code className="font-mono text-[12px] text-emerald-200">ai-trader/deploy</code></h2>
      <div className="mt-3 grid grid-cols-1 gap-2 lg:grid-cols-2">
        {COMMANDS.map(([cmd, what], i) => (
          <div key={cmd} className="space-y-1">
            <CodeBlock cmd={cmd} where={what} testId={`vps-cmd-${i}`} />
          </div>
        ))}
      </div>
    </section>
  );
}

function Trouble() {
  return (
    <section data-testid="vps-trouble" className="rounded-md border border-[#1E293B] bg-[#0D111A] p-5">
      <h2 className="flex items-center gap-2 font-display text-[14px] font-semibold text-slate-100"><LifeBuoy className="h-4 w-4 text-emerald-400" /> Problemas frecuentes</h2>
      <Accordion type="multiple" className="mt-1">
        {TROUBLE.map(([q, a], i) => (
          <AccordionItem key={q} value={`t-${i}`} className="border-[#1E293B]">
            <AccordionTrigger data-testid={`vps-trouble-${i}`} className="py-3 text-left text-[13px] text-slate-200 hover:text-emerald-200 hover:no-underline">{q}</AccordionTrigger>
            <AccordionContent className="text-[12.5px] leading-relaxed text-slate-400">{a}</AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </section>
  );
}

export default function VpsInstall({ onBack }) {
  return (
    <div data-testid="vps-install-view" className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-emerald-500/40 bg-emerald-500/10 text-emerald-300"><Server className="h-5 w-5" /></span>
          <div>
            <h1 className="font-display text-xl font-bold text-slate-50 md:text-2xl">Instalar en tu VPS</h1>
            <p className="text-[12px] text-slate-500">Lleva los tres bots a tu propio servidor: descarga el paquete completo y sigue la guía detallada. Los comandos se copian con un clic.</p>
          </div>
        </div>
        {onBack && <Button data-testid="vps-back-button" variant="outline" size="sm" onClick={onBack} className="h-8 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider hover:bg-[#111827]"><ArrowLeft className="mr-1.5 h-3.5 w-3.5" /> Volver al panel</Button>}
      </div>
      <VpsDownloadCard />
      <Requirements />
      <VpsSteps />
      <Commands />
      <Trouble />
      <p className="pb-2 font-mono text-[10px] uppercase tracking-wider text-slate-600">La misma guía viaja dentro del zip en deploy/INSTALACION.md · El trading con apalancamiento implica alto riesgo: prueba en paper antes de pasar a REAL</p>
    </div>
  );
}
