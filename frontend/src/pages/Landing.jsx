import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  ArrowRight, Activity, Eye, EarOff, Accessibility, MousePointerClick, Globe, ShieldCheck,
  Play, Sparkles, Gauge, Smartphone, FileText, GitCompare, Mic, Wand2, GitPullRequest,
} from "lucide-react";

import SiteHeader from "@/components/SiteHeader";
import BenchmarkMarquee from "@/components/BenchmarkMarquee";
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
  { t: "00:01", msg: "/atmos test → yourapp.com" },
  { t: "00:04", msg: "Crawl + VLM explore · 6 screens" },
  { t: "00:09", msg: "A11y audit · contrast + ARIA + keyboard" },
  { t: "00:14", msg: "Personas · elderly 71 · blind 64" },
  { t: "00:18", msg: "Competitive vs Stripe · 2 gaps" },
  { t: "00:22", msg: "Craft Score 78 → gate PASS (≥70)" },
  { t: "00:23", msg: "Δ +4 vs baseline run_a3f2" },
  { t: "00:24", msg: "PR craft gate ready for CI" },
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

      <section className="relative overflow-hidden">
        <div className="absolute inset-0 dot-grid opacity-60 pointer-events-none" />
        <div className="absolute inset-0 bg-gradient-to-b from-[#F5F5F7]/80 via-white/40 to-white pointer-events-none" />
        <div className="max-w-7xl mx-auto px-6 md:px-8 pt-20 md:pt-28 pb-20 md:pb-28 grid lg:grid-cols-12 gap-10 lg:gap-14 items-end relative">
          <div className="lg:col-span-7">
            <div className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-6">Atmos</div>
            <h1 className="font-display text-5xl sm:text-6xl lg:text-7xl tracking-tighter font-medium leading-[1.02]">
              The craft score for software.
            </h1>
            <p className="mt-6 text-lg md:text-xl text-[#1D1D1F]/70 max-w-2xl leading-relaxed">
              Construction is cheap. Judgment is scarce. Atmos measures whether your product feels top-tier —
              accessibility, personas, design, funnel, competitive parity, dark-pattern integrity — and gates PRs on the result.
            </p>

            <div className="mt-9 flex items-center gap-3">
              <Link to="/login">
                <Button
                  size="lg"
                  className="rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white px-7 h-12 text-base"
                  data-testid="hero-cta-primary"
                >
                  Get your Craft Score <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Link>
              <a href="#how">
                <Button
                  variant="outline"
                  size="lg"
                  className="rounded-full px-6 h-12 text-base border-black/10"
                  data-testid="hero-cta-secondary"
                >
                  <Play className="mr-2 h-4 w-4" /> See the loop
                </Button>
              </a>
            </div>

            <div className="mt-10 flex flex-wrap items-center gap-6 text-sm text-[#1D1D1F]/60">
              <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Real Playwright evidence</div>
              <div className="flex items-center gap-2"><GitPullRequest className="h-4 w-4" /> CI craft gate</div>
              <div className="flex items-center gap-2"><Gauge className="h-4 w-4" /> Baseline deltas</div>
            </div>
          </div>

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
                  <div className="text-[10px] uppercase tracking-[0.2em] text-white/40">craft · live</div>
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" />
                </div>
                <div className="space-y-1.5 max-h-72 overflow-hidden">
                  {TERMINAL_LINES.map((l, i) => (
                    <div
                      key={i}
                      className={`flex gap-3 transition-opacity duration-500 ${i <= activeLine ? "opacity-100" : "opacity-30"}`}
                    >
                      <span className="text-white/30 tabular-nums">{l.t}</span>
                      <span className="text-white/85">{l.msg}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <BenchmarkMarquee />

      <section id="how" className="bg-[#F5F5F7]">
        <div className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32 grid lg:grid-cols-2 gap-16 items-center">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">The craft loop</div>
            <h2 className="font-display text-3xl md:text-4xl lg:text-5xl tracking-tight font-medium leading-tight">
              Thesis → probe → evidence → score → gate.
            </h2>
            <p className="mt-6 text-lg text-[#1D1D1F]/70 leading-relaxed">
              Atmos runs a real browser against your URL or GitHub app, gathers measurable evidence,
              computes a Craft Score, compares to your last baseline, and fails CI when craft regresses.
            </p>
            <ul className="mt-8 space-y-4 text-[#1D1D1F]/80">
              {[
                "Playwright crawl, VLM exploration, fuzz, a11y, personas — not sleep theater.",
                "Craft Score blends accessibility, personas, UX, design, funnel, competitive parity, and integrity.",
                "Baseline Δ on every run; PR gate via GitHub Action + craft_api_token.",
                "IDE-native LLM on your quota — Cursor / VS Code extension.",
              ].map((t, i) => (
                <li key={i} className="flex gap-3">
                  <span className="mt-1 w-1.5 h-1.5 rounded-full bg-[#0071E3] shrink-0" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card-elev p-6 md:p-8">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B]">Craft Score</div>
            <div className="mt-2 font-display text-7xl tabular-nums tracking-tight text-[#34C759]">78</div>
            <div className="text-sm text-[#86868B]">competitive · gate PASS · Δ +4</div>
            <div className="mt-6 grid grid-cols-2 gap-3 text-sm">
              {[
                ["accessibility", 84],
                ["personas", 72],
                ["design", 81],
                ["funnel", 69],
              ].map(([k, v]) => (
                <div key={k} className="rounded-xl bg-[#F5F5F7] p-3">
                  <div className="text-[10px] uppercase tracking-wider text-[#86868B]">{k}</div>
                  <div className="font-display text-2xl tabular-nums mt-1">{v}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="commands" className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-12">
          <div className="max-w-2xl">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Lenses</div>
            <h2 className="font-display text-3xl md:text-4xl lg:text-5xl tracking-tight font-medium">
              Specialized runs. <span className="text-[#86868B]">One Craft Score.</span>
            </h2>
          </div>
          <p className="text-[#1D1D1F]/70 max-w-md text-base">
            Each `/atmos` command specializes the pipeline — accessibility deep audit, mobile, demand, full suite — then rolls into the same score.
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

      <section id="personas" className="bg-[#F5F5F7]">
        <div className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32">
          <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Human simulation</div>
          <h2 className="font-display text-3xl md:text-4xl tracking-tight font-medium max-w-2xl">
            Seven personas. Measured rules. Video evidence.
          </h2>
          <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {PERSONAS.map((p) => {
              const Icon = p.icon;
              return (
                <div key={p.name} className="card-elev p-5">
                  <Icon className="h-4 w-4 text-[#1D1D1F]" strokeWidth={1.5} />
                  <div className="mt-3 font-display text-lg font-medium">{p.name}</div>
                  <div className="mt-1 text-sm text-[#1D1D1F]/65">{p.focus}</div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-6 md:px-8 py-24 md:py-32 text-center">
        <h2 className="font-display text-4xl md:text-5xl tracking-tight font-medium">
          Make craft a merge requirement.
        </h2>
        <p className="mt-4 text-[#1D1D1F]/70 max-w-xl mx-auto">
          Drop in the Atmos Craft Gate GitHub Action. Fail PRs when judgment regresses.
        </p>
        <Link to="/login">
          <Button
            size="lg"
            className="mt-8 rounded-full bg-[#1D1D1F] hover:bg-black text-white px-8 h-12"
            data-testid="footer-cta"
          >
            Start free <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </Link>
      </section>
    </div>
  );
}
