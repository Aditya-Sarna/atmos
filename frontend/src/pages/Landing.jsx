import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  ArrowRight, Activity, Eye, EarOff, Accessibility, MousePointerClick, Globe, ShieldCheck,
  Play, Sparkles, Gauge, Smartphone, FileText, GitCompare, Mic, Wand2,
} from "lucide-react";

import SiteHeader from "@/components/SiteHeader";
import BenchmarkMarquee from "@/components/BenchmarkMarquee";
import AtmosMark from "@/components/AtmosMark";
import { Button } from "@/components/ui/button";
import { listCommands } from "@/lib/api";

const COMMAND_ICONS = {
  "/atmos analyze": Sparkles,
  "/atmos explore": MousePointerClick,
  "/atmos test": Activity,
  "/atmos regress": GitCompare,
  "/atmos mobile": Smartphone,
  "/atmos benchmark": Gauge,
  "/atmos accessibility": Accessibility,
  "/atmos personas": Eye,
  "/atmos record": Mic,
  "/atmos report": FileText,
};

const PERSONAS = [
  { name: "Elderly (65+)", focus: "Vision, dexterity, slow reading", icon: Eye },
  { name: "Blind", focus: "Screen reader, keyboard-only", icon: EarOff },
  { name: "Low-Vision", focus: "200–400% zoom", icon: Eye },
  { name: "Color-Blind", focus: "Protanopia / Deuteranopia / Tritanopia", icon: Eye },
  { name: "First-Time", focus: "Discoverability, confusion points", icon: MousePointerClick },
  { name: "Power User", focus: "Shortcuts, workflow efficiency", icon: Wand2 },
  { name: "Child", focus: "Readability, misclick potential", icon: Globe },
];

const TERMINAL_LINES = [
  { t: "00:01", msg: "/atmos test → stripe.com" },
  { t: "00:02", msg: "Detected archetype: finance" },
  { t: "00:03", msg: "Building application graph…" },
  { t: "00:05", msg: "Probing CTA visibility on iPhone SE…" },
  { t: "00:07", msg: "warn  CTA overlaps footer at 375×667" },
  { t: "00:09", msg: "Simulating Elderly persona…" },
  { t: "00:11", msg: "crit  inputs missing aria-label on SignIn" },
  { t: "00:13", msg: "Benchmark: 7 clicks to checkout (industry 4)" },
  { t: "00:15", msg: "Generating executive report…" },
];

export default function Landing() {
  const [commands, setCommands] = useState([]);
  const [activeLine, setActiveLine] = useState(0);

  useEffect(() => {
    listCommands().then((r) => setCommands(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    const i = setInterval(() => setActiveLine((n) => (n + 1) % TERMINAL_LINES.length), 1400);
    return () => clearInterval(i);
  }, []);

  return (
    <div className="min-h-screen bg-white" data-testid="landing-page">
      <SiteHeader variant="marketing" />

      {/* HERO */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 dot-grid opacity-60 pointer-events-none" />
        <div className="max-w-7xl mx-auto px-6 md:px-8 pt-20 md:pt-28 pb-20 md:pb-28 grid lg:grid-cols-12 gap-10 lg:gap-14 items-end relative">
          <div className="lg:col-span-7">
            <div className="inline-flex items-center gap-2 rounded-full border border-black/10 bg-white px-3 py-1 text-xs text-[#1D1D1F]/70 mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-[#34C759] live-dot" />
              Now in beta · /atmos
            </div>
            <h1 className="font-display text-5xl sm:text-6xl lg:text-7xl tracking-tighter font-medium leading-[1.02]">
              The testing agent that <span className="text-[#86868B]">watches your product</span> like a real user.
            </h1>
            <p className="mt-6 text-lg md:text-xl text-[#1D1D1F]/70 max-w-2xl leading-relaxed">
              Atmos understands context, generates intelligent test plans, explores your app
              autonomously, records video evidence, and benchmarks the result against the best products in the world.
            </p>


            <div className="mt-9 flex items-center gap-3">
              <Link to="/login">
                <Button
                  size="lg"
                  className="rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white px-7 h-12 text-base"
                  data-testid="hero-cta-primary"
                >
                  Start a free run <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
              <a href="#how">
                <Button
                  variant="outline"
                  size="lg"
                  className="rounded-full px-6 h-12 text-base border-black/10"
                  data-testid="hero-cta-secondary"
                >
                  <Play className="mr-2 h-4 w-4" /> See it think
                </Button>
              </a>
            </div>

            <div className="mt-10 flex items-center gap-6 text-sm text-[#1D1D1F]/60">
              <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> WCAG AAA-aware</div>
              <div className="flex items-center gap-2"><Activity className="h-4 w-4" /> Live, observable runs</div>
              <div className="flex items-center gap-2"><Gauge className="h-4 w-4" /> Benchmarked output</div>
            </div>
          </div>

          {/* Terminal preview */}
          <div className="lg:col-span-5">
            <div className="relative">
              <div className="absolute -inset-6 rounded-[36px] bg-gradient-to-br from-[#F5F5F7] to-white -z-10" />
              <div className="terminal p-5 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.35)]">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full bg-[#FF3B30]/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#FF9500]/80" />
                    <span className="w-2.5 h-2.5 rounded-full bg-[#34C759]/80" />
                  </div>
                  <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">live · atmos</div>
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" />
                </div>
                <div className="space-y-1.5 max-h-72 overflow-hidden">
                  {TERMINAL_LINES.map((l, i) => (
                    <div
                      key={i}
                      className={`flex gap-3 transition-opacity ${i <= activeLine ? "opacity-100" : "opacity-30"}`}
                    >
                      <span className="text-white/30 tabular-nums">{l.t}</span>
                      <span className={l.msg.startsWith("warn") ? "text-[#FF9500]" : l.msg.startsWith("crit") ? "text-[#FF3B30]" : "text-white/85"}>
                        {l.msg}
                      </span>
                    </div>
                  ))}
                  <div className="flex gap-3 items-center pt-1">
                    <span className="text-white/30 tabular-nums">▌</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <BenchmarkMarquee />

      {/* COMMANDS */}
      <section id="commands" className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-12">
          <div className="max-w-2xl">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Primary commands</div>
            <h2 className="font-display text-3xl md:text-4xl lg:text-5xl tracking-tight font-medium">
              Ten verbs. <span className="text-[#86868B]">One autonomous tester.</span>
            </h2>
          </div>
          <p className="text-[#1D1D1F]/70 max-w-md text-base">
            Each command shifts the agent&apos;s lens — from architecture analysis to persona simulation to executive reporting.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3" data-testid="commands-grid">
          {commands.map((c, i) => {
            const Icon = COMMAND_ICONS[c.cmd] || Activity;
            return (
              <div
                key={c.cmd}
                className="card-elev p-5 hover:border-[#1D1D1F]/20 transition-all duration-300 anim-slide-up"
                style={{ animationDelay: `${i * 40}ms` }}
                data-testid={`command-card-${c.label.toLowerCase()}`}
              >
                <Icon className="h-5 w-5 text-[#1D1D1F]" strokeWidth={1.5} />
                <div className="mt-4 font-mono text-xs text-[#86868B]">{c.cmd}</div>
                <div className="mt-1 font-display text-lg font-medium">{c.label}</div>
                <div className="mt-1 text-sm text-[#1D1D1F]/65 leading-snug">{c.desc}</div>
              </div>
            );
          })}
        </div>
      </section>

      {/* HOW */}
      <section id="how" className="bg-[#F5F5F7]">
        <div className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32 grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">How it works</div>
            <h2 className="font-display text-3xl md:text-4xl lg:text-5xl tracking-tight font-medium leading-tight">
              Paste a URL. Watch Atmos work.
            </h2>
            <p className="mt-6 text-lg text-[#1D1D1F]/70 leading-relaxed">
              Real-time activity feed. Live screenshots. Live persona scores. Live root-cause analysis.
              When the run completes, you get an executive report with concrete next steps.
            </p>
            <ul className="mt-8 space-y-4 text-[#1D1D1F]/80">
              {[
                "Detects archetype: finance, e-commerce, calendar, dashboard, or generic.",
                "Generates a context-aware plan via Claude Sonnet 4.5.",
                "Explores your UI like seven different humans simultaneously.",
                "Benchmarks against Apple, Stripe, Linear, Notion — by the click.",
              ].map((t, i) => (
                <li key={i} className="flex gap-3">
                  <span className="mt-1 w-1.5 h-1.5 rounded-full bg-[#0071E3] shrink-0" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="relative">
            <div className="card-elev p-6 md:p-8">
              <div className="flex items-center justify-between text-xs text-[#86868B] uppercase tracking-[0.2em]">
                <span>Live monitor preview</span>
                <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" /> live</span>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3">
                {["Accessibility", "UX", "Reliability"].map((s, i) => (
                  <div key={s} className="rounded-2xl bg-[#F5F5F7] p-4">
                    <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{s}</div>
                    <div className="mt-2 font-display text-3xl tabular-nums font-medium">
                      {[88, 81, 92][i]}
                    </div>
                    <div className="text-xs text-[#86868B] mt-1">/ 100</div>
                  </div>
                ))}
              </div>
              <div className="mt-5 terminal p-4 max-h-44 overflow-hidden">
                <div className="space-y-1">
                  <div><span className="text-white/30">10:14:02</span>  <span className="text-white/85">Probing checkout flow…</span></div>
                  <div><span className="text-white/30">10:14:04</span>  <span className="text-[#FF9500]">warn  TouchTarget 32px &lt; 44px on Pay button</span></div>
                  <div><span className="text-white/30">10:14:06</span>  <span className="text-[#FF3B30]">crit  Currency precision drift at $9,999.99+</span></div>
                  <div><span className="text-white/30">10:14:09</span>  <span className="text-white/85">Persona &ldquo;Color-Blind&rdquo; — status only by color ↘</span></div>
                  <div><span className="text-white/30">10:14:11</span>  <span className="text-white/85">Comparing flow vs Stripe…</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* PERSONAS */}
      <section id="personas" className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32">
        <div className="max-w-2xl mb-12">
          <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Persona simulation</div>
          <h2 className="font-display text-3xl md:text-4xl lg:text-5xl tracking-tight font-medium leading-tight">
            Seven humans test your product, <span className="text-[#86868B]">not seven assertions.</span>
          </h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3" data-testid="personas-grid">
          {PERSONAS.map((p, i) => (
            <div
              key={p.name}
              className="card-elev p-5 anim-slide-up"
              style={{ animationDelay: `${i * 40}ms` }}
              data-testid={`persona-card-${p.name.toLowerCase().replace(/[^a-z]+/g, "-")}`}
            >
              <p.icon className="h-5 w-5" strokeWidth={1.5} />
              <div className="mt-4 font-display text-lg font-medium">{p.name}</div>
              <div className="mt-1 text-sm text-[#1D1D1F]/65 leading-snug">{p.focus}</div>
            </div>
          ))}
        </div>
      </section>

      {/* BENCHMARKS */}
      <section id="benchmarks" className="bg-[#1D1D1F] text-white">
        <div className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32">
          <div className="grid lg:grid-cols-12 gap-10 items-end">
            <div className="lg:col-span-7">
              <div className="text-xs uppercase tracking-[0.2em] text-white/40 mb-3">Competitive benchmark</div>
              <h2 className="font-display text-3xl md:text-4xl lg:text-5xl tracking-tight font-medium leading-tight">
                The bar is <span className="text-white/50">the best product in your category.</span>
              </h2>
              <p className="mt-6 text-lg text-white/65 max-w-2xl leading-relaxed">
                Atmos compares your flows, micro-copy, click counts, and information density against
                category leaders — and tells you exactly where you fall behind.
              </p>
            </div>
            <div className="lg:col-span-5">
              <div className="border border-white/15 rounded-2xl p-6">
                <div className="text-[11px] uppercase tracking-[0.2em] text-white/40">Your checkout</div>
                <div className="mt-2 font-display text-4xl tabular-nums">7 clicks</div>
                <div className="mt-4 h-px bg-white/15" />
                <div className="mt-4 text-[11px] uppercase tracking-[0.2em] text-white/40">Industry benchmark</div>
                <div className="mt-2 font-display text-4xl tabular-nums text-[#34C759]">4 clicks</div>
                <div className="mt-5 text-sm text-white/65">
                  Suggested fix: expose checkout entry point globally; collapse address & shipping into one step.
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32 text-center">
        <h2 className="font-display text-4xl md:text-5xl lg:text-6xl tracking-tighter font-medium leading-[1.05]">
          Ship products that work for everyone.
        </h2>
        <p className="mt-6 text-lg text-[#1D1D1F]/70 max-w-2xl mx-auto">
          One command, every viewport, every persona, every benchmark. Atmos returns video,
          screenshots, root causes, and the five things to fix first.
        </p>
        <Link to="/login">
          <Button
            size="lg"
            className="mt-10 rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white px-8 h-12 text-base"
            data-testid="footer-cta-primary"
          >
            Start a free run <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </Link>
      </section>

      <footer className="border-t border-black/5">
        <div className="max-w-7xl mx-auto px-6 md:px-8 py-10 flex flex-col md:flex-row items-center justify-between gap-4">
          <AtmosMark size={24} />
          <div className="text-sm text-[#86868B]">© {new Date().getFullYear()} Atmos · Autonomous Product Testing.</div>
        </div>
      </footer>
    </div>
  );
}
