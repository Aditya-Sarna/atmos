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
