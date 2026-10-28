import { useMemo, useState } from "react";
import * as Icons from "lucide-react";
import { BookOpen, Search, Sparkles, ListChecks, MessageCircleQuestion, ArrowLeft } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { buildFeatures } from "./featuresContent";
import { buildHowTo } from "./howToContent";
import { buildFaq } from "./faqContent";

const TAB = "rounded-sm px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-slate-400 data-[state=active]:bg-amber-500 data-[state=active]:text-[#07090E]";
const Icon = ({ name, className }) => { const C = Icons[name] || Icons.Circle; return <C className={className} />; };
const BRAND = {
  pepper: { name: "Pepperstone AI trading", accent: "text-teal-300", chip: "border-teal-500/40 bg-teal-500/10 text-teal-300", sub: "Forex y metales · Razor / Standard · horario de mercado" },
  crypto: { name: "Bybit AI Trader", accent: "text-amber-400", chip: "border-amber-500/40 bg-amber-500/10 text-amber-300", sub: "Futuros perpetuos USDT · cripto 24/7" },
  fx: { name: "HotForex AI Trading", accent: "text-sky-400", chip: "border-sky-500/40 bg-sky-500/10 text-sky-300", sub: "Forex y metales · horario de mercado" },
};
// Pepperstone shares the FX docs; broker names, suffix talk and the settings tab name are swapped in the generated text.
const PEP_SWAPS = [
  ["HotForex AI Trading", "Pepperstone AI trading"], ["Ajustes → HotForex", "Ajustes → Pepperstone"], ["HFM (HotForex)", "Pepperstone"], ["HotForex", "Pepperstone"],
  ["tipo de cuenta HFM (Premium sin sufijo, Zero «b», Pro «r», Cent «c», InfinityX «x»)", "tipo de cuenta (en Pepperstone los símbolos no llevan sufijo)"],
  ["Premium sin sufijo (EURUSD), Zero «b» (EURUSDb), Pro «r» (EURUSDr), Cent «c» (EURUSDc), InfinityX «x»", "en Pepperstone todos los tipos de cuenta usan el símbolo sin sufijo (EURUSD, XAUUSD)"],
  ["HFMarketsGlobal-Live2", "Pepperstone-MT5-Live01"], ["spread medio de HFM", "spread y comisión de tu tipo de cuenta Pepperstone (Razor o Standard)"], ["Spread medio de HFM", "Spread y comisión de tu tipo de cuenta Pepperstone (Razor o Standard)"],
  ["HFM", "Pepperstone"],
];
const rebrand = (node, bot) => {
  if (bot !== "pepper") return node;
  if (typeof node === "string") return node.includes("Pepperstone") ? node : PEP_SWAPS.reduce((s, [a, b]) => s.split(a).join(b), node);  // pepper-aware strings are left as written
  if (Array.isArray(node)) return node.map((n) => rebrand(n, bot));
  if (node && typeof node === "object") return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, rebrand(v, bot)]));
  return node;
};


function Features({ data, brand }) {
  return (
    <div className="space-y-6">
      <div data-testid="docs-hero" className="rounded-md border border-[#1E293B] bg-[#0D111A] p-6 md:p-8">
        <p className={`font-mono text-[10px] uppercase tracking-[0.2em] ${brand.accent}`}>Características</p>
        <h2 className="font-display mt-2 max-w-3xl text-xl font-bold leading-snug text-slate-50 md:text-2xl">{data.hero.title}</h2>
        <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-slate-300">{data.hero.text}</p>
        <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[#1E293B] bg-[#1E293B] sm:grid-cols-3 lg:grid-cols-6">
          {data.hero.stats.map(([v, l]) => (
            <div key={l} className="bg-[#07090E] px-4 py-3"><p className={`font-display text-xl font-bold ${brand.accent}`}>{v}</p><p className="mt-0.5 text-[11px] text-slate-400">{l}</p></div>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {data.sections.map((s, i) => (
          <article key={s.title} data-testid={`docs-feature-${i}`} className="rise rounded-md border border-[#1E293B] bg-[#0D111A] p-5" style={{ animationDelay: `${i * 40}ms` }}>
            <div className="flex items-start gap-3">
              <span className={`mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border ${brand.chip}`}><Icon name={s.icon} className="h-4 w-4" /></span>
              <div>
                <h3 className="font-display text-[14px] font-semibold text-slate-100">{s.title}</h3>
                <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{s.text}</p>
              </div>
            </div>
            <ul className="mt-3 space-y-1.5 pl-1">
              {s.bullets.filter(Boolean).map((b, j) => <li key={j} className="flex gap-2 text-[12px] leading-relaxed text-slate-300"><span className={`mt-[7px] h-1 w-1 shrink-0 rounded-full ${brand.accent.replace("text-", "bg-")}`} />{b}</li>)}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}

function HowTo({ data, brand }) {
  const [active, setActive] = useState(data[0].id);
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
      <nav data-testid="docs-howto-index" className="thin-scroll lg:sticky lg:top-4 lg:max-h-[calc(100vh-120px)] lg:overflow-auto">
        <div className="rounded-md border border-[#1E293B] bg-[#0D111A] p-2">
          {data.map((g) => (
            <a key={g.id} href={`#docs-${g.id}`} data-testid={`docs-howto-link-${g.id}`} onClick={() => setActive(g.id)}
              className={`flex items-center gap-2 rounded-sm px-2.5 py-2 text-[12px] transition-colors ${active === g.id ? "bg-[#111827] text-amber-300" : "text-slate-400 hover:bg-[#111827] hover:text-slate-200"}`}>
              <Icon name={g.icon} className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{g.title.replace(/^\d+ · /, "")}</span>
            </a>
          ))}
        </div>
      </nav>
      <div className="space-y-4">
        {data.map((g) => (
          <section key={g.id} id={`docs-${g.id}`} data-testid={`docs-howto-${g.id}`} className="scroll-mt-4 rounded-md border border-[#1E293B] bg-[#0D111A] p-5">
            <h3 className="flex items-center gap-2 font-display text-[14px] font-semibold text-slate-100"><Icon name={g.icon} className={`h-4 w-4 ${brand.accent}`} /> {g.title}</h3>
            <ol className="mt-3 space-y-2.5">
              {g.steps.map((st, i) => (
                <li key={i} className="flex gap-3 text-[12.5px] leading-relaxed text-slate-300">
                  <span className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm border font-mono text-[10px] ${brand.chip}`}>{i + 1}</span><span>{st}</span>
                </li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}

function Faq({ data, brand }) {
  const [q, setQ] = useState("");
  const cats = useMemo(() => [...new Set(data.map((f) => f.cat))], [data]);
  const term = q.trim().toLowerCase();
  const filtered = term ? data.filter((f) => `${f.q} ${f.a} ${f.tags.join(" ")}`.toLowerCase().includes(term)) : data;
  return (
    <div className="space-y-4">
      <div className="relative max-w-xl">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        <Input data-testid="docs-faq-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar una pregunta… (p. ej. telegram, depósito, no opera)" className="h-9 border-[#1E293B] bg-[#0D111A] pl-9 text-[13px] text-slate-100 placeholder:text-slate-600" />
      </div>
      <p data-testid="docs-faq-count" className="font-mono text-[10px] uppercase tracking-wider text-slate-500">{filtered.length} de {data.length} preguntas</p>
      {cats.map((cat) => {
        const items = filtered.filter((f) => f.cat === cat);
        if (!items.length) return null;
        return (
          <section key={cat} data-testid={`docs-faq-cat-${cat.replace(/[^a-z]/gi, "-").toLowerCase()}`} className="rounded-md border border-[#1E293B] bg-[#0D111A] p-4">
            <h3 className={`font-mono text-[10px] uppercase tracking-[0.18em] ${brand.accent}`}>{cat}</h3>
            <Accordion type="multiple" className="mt-1">
              {items.map((f, i) => (
                <AccordionItem key={f.q} value={`${cat}-${i}`} className="border-[#1E293B]">
                  <AccordionTrigger data-testid={`docs-faq-q-${data.indexOf(f)}`} className="py-3 text-left text-[13px] text-slate-200 hover:no-underline hover:text-amber-200">{f.q}</AccordionTrigger>
                  <AccordionContent className="text-[12.5px] leading-relaxed text-slate-400">{f.a}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </section>
        );
      })}
      {!filtered.length && <p data-testid="docs-faq-empty" className="text-[12px] text-slate-500">No hay preguntas que coincidan. Prueba con otra palabra o escríbenos tu duda desde el chat.</p>}
    </div>
  );
}

export default function Documentation({ bot = "crypto", onBack }) {
  const brand = BRAND[bot];
  const features = useMemo(() => rebrand(buildFeatures(bot), bot), [bot]);
  const howto = useMemo(() => rebrand(buildHowTo(bot), bot), [bot]);
  const faq = useMemo(() => rebrand(buildFaq(bot), bot), [bot]);
  return (
    <div data-testid="documentation-view" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className={`inline-flex h-10 w-10 items-center justify-center rounded-md border ${brand.chip}`}><BookOpen className="h-5 w-5" /></span>
          <div>
            <h1 className="font-display text-xl font-bold text-slate-50 md:text-2xl">Documentación · {brand.name}</h1>
            <p className="text-[12px] text-slate-500">{brand.sub} · todo lo que hace el bot, cómo usarlo paso a paso y respuestas a las dudas más comunes.</p>
          </div>
        </div>
        {onBack && <Button data-testid="docs-back-button" variant="outline" size="sm" onClick={onBack} className="h-8 border-[#1E293B] bg-transparent font-mono text-[11px] uppercase tracking-wider hover:bg-[#111827]"><ArrowLeft className="mr-1.5 h-3.5 w-3.5" /> Volver al panel</Button>}
      </div>
      <Tabs defaultValue="features">
        <TabsList data-testid="docs-tabs" className="h-auto flex-wrap justify-start gap-1 rounded-md border border-[#1E293B] bg-[#0D111A] p-1">
          <TabsTrigger data-testid="docs-tab-features" value="features" className={TAB}><Sparkles className="mr-1.5 h-3.5 w-3.5" /> Características</TabsTrigger>
          <TabsTrigger data-testid="docs-tab-howto" value="howto" className={TAB}><ListChecks className="mr-1.5 h-3.5 w-3.5" /> Cómo usar</TabsTrigger>
          <TabsTrigger data-testid="docs-tab-faq" value="faq" className={TAB}><MessageCircleQuestion className="mr-1.5 h-3.5 w-3.5" /> Preguntas y respuestas</TabsTrigger>
        </TabsList>
        <TabsContent value="features" className="mt-4"><Features data={features} brand={brand} /></TabsContent>
        <TabsContent value="howto" className="mt-4"><HowTo data={howto} brand={brand} /></TabsContent>
        <TabsContent value="faq" className="mt-4"><Faq data={faq} brand={brand} /></TabsContent>
      </Tabs>
    </div>
  );
}
