import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getRun, BACKEND_URL, applyPatch } from "@/lib/api";
import { toast } from "sonner";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import AtmosMark from "@/components/AtmosMark";
import { TestCaseList, TestCaseTheatre } from "@/components/TestCases";
import IssueDiffCard from "@/components/IssueDiffCard";
import RealShot from "@/components/RealShot";
import AppGraph from "@/components/AppGraph";
import ChaosLabPanel from "@/components/ChaosLabPanel";
import DopaminePanel from "@/components/DopaminePanel";
import MarkdownView from "@/components/MarkdownView";
import {
  ArrowUpRight, Eye, FileText, Activity, AlertTriangle, AlertOctagon,
  MousePointerClick, Smartphone, Gauge, Sparkles, GitCompare, Accessibility, Mic, CheckCircle2, FlaskConical,
  Github, Layers, Radio, Users, CreditCard,
} from "lucide-react";

const PHASE_ICONS = {
  analyze: Sparkles, explore: MousePointerClick, mobile: Smartphone,
  accessibility: Accessibility, personas: Eye, issues: AlertTriangle,
  test_cases: FlaskConical, benchmark: Gauge, report: FileText,
  github_boot: Github, per_page: Sparkles, fuzz: FlaskConical, architecture: Layers,
};
const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };
const SCREEN_VERDICT_COLOR = { pass: "#34C759", warn: "#FF9500", fail: "#FF3B30" };

function MockBrowser({ url, action, target, viewport }) {
  return (
    <div className="rounded-xl bg-white border border-black/10 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-black/5 bg-[#F5F5F7]">
        <span className="w-2 h-2 rounded-full bg-[#FF3B30]/70" />
        <span className="w-2 h-2 rounded-full bg-[#FF9500]/70" />
        <span className="w-2 h-2 rounded-full bg-[#34C759]/70" />
        <div className="flex-1 mx-3 px-3 py-1 rounded-md bg-white border border-black/5 text-[11px] text-[#86868B] truncate font-mono">
          {url}
        </div>
        <span className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{viewport || "Desktop"}</span>
      </div>
      <div className="relative aspect-[16/10] bg-gradient-to-br from-[#F5F5F7] via-white to-[#EEF3FA]">
        <div className="absolute inset-0 dot-grid opacity-50" />
        <div className="absolute top-6 left-6 right-6 h-8 rounded-md bg-white shadow-sm border border-black/5" />
        <div className="absolute top-20 left-6 w-2/3 h-3 rounded bg-[#1D1D1F]/80" />
        <div className="absolute top-28 left-6 w-1/2 h-2 rounded bg-[#86868B]/50" />
        <div className="absolute top-36 left-6 right-6 grid grid-cols-3 gap-3">
          <div className="aspect-square rounded-xl bg-white border border-black/5 shadow-sm" />
          <div className="aspect-square rounded-xl bg-white border border-black/5 shadow-sm" />
          <div className="aspect-square rounded-xl bg-white border border-black/5 shadow-sm" />
        </div>
        <div className="absolute bottom-6 left-6 right-6 flex items-center justify-between">
          <div className="h-9 w-28 rounded-full bg-[#0071E3]" />
          <div className="h-9 w-20 rounded-full bg-[#1D1D1F]/10" />
        </div>
        {action && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="rounded-full bg-[#1D1D1F] text-white text-xs px-3 py-1.5 shadow-lg flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF3B30] live-dot" />
              {action} → {target}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ScoreRing({ value, label, color = "#0071E3" }) {
  const v = Math.max(0, Math.min(100, value || 0));
  const c = 2 * Math.PI * 36;
  const offset = c - (c * v) / 100;
  return (
    <div className="flex flex-col items-center" data-testid={`score-ring-${label.toLowerCase()}`}>
      <svg width="92" height="92" viewBox="0 0 92 92">
        <circle cx="46" cy="46" r="36" stroke="#EFEFF4" strokeWidth="8" fill="none" />
        <circle
          cx="46" cy="46" r="36" stroke={color} strokeWidth="8" fill="none"
          strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
          transform="rotate(-90 46 46)"
        />
        <text x="46" y="52" textAnchor="middle" className="font-display" fontSize="22" fill="#1D1D1F" fontWeight="500">
          {v}
        </text>
      </svg>
      <div className="mt-2 text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
    </div>
  );
}

function architectureText(value) {
  if (value == null) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(architectureText).filter(Boolean).join(" · ");
  if (typeof value === "object") {
    return [value.title, value.name, value.label, value.summary, value.detail, value.takeaway, value.what_they_do_better, value.what_to_copy, value.score]
      .filter((item) => item != null && item !== "")
      .map(String)
      .join(" · ");
  }
  return String(value);
}

export default function RunMonitor() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [run, setRun] = useState(null);
  const [project, setProject] = useState(null);
  const [events, setEvents] = useState([]);
  const [done, setDone] = useState(false);
  const feedRef = useRef(null);

  // Hydrate from API once
  useEffect(() => {
    getRun(runId).then((r) => {
      setRun(r.data.run);
      setProject(r.data.project);
      setEvents(r.data.events || []);
      if (r.data.run?.status === "completed" || r.data.run?.status === "failed") {
        setDone(true);
      }
    }).catch(() => navigate("/dashboard", { replace: true }));
  }, [runId, navigate]);

  // SSE
  useEffect(() => {
    const es = new EventSource(`${BACKEND_URL}/api/runs/${runId}/stream`, { withCredentials: true });
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        setEvents((prev) => {
          if (prev.some((p) => p.seq === data.seq)) return prev;
          return [...prev, data].sort((a, b) => a.seq - b.seq);
        });
      } catch {
        /* ignore malformed event */
      }
    };
    es.addEventListener("done", () => {
      setDone(true);
      getRun(runId).then((r) => setRun(r.data.run)).catch(() => {});
      es.close();
    });
    es.onerror = () => { es.close(); };
    return () => es.close();
  }, [runId]);

  // Auto-scroll log
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [events]);

  const logs = events.filter((e) => e.kind === "log");
  const phases = events.filter((e) => e.kind === "phase");
  const screenshots = events.filter((e) => e.kind === "screenshot");
  const viewports = events.filter((e) => e.kind === "viewport");
  const personas = events.filter((e) => e.kind === "persona");
  const personaAnnotations = events.filter((e) => e.kind === "persona_annotation");
  const funnelAnalysis = events.filter((e) => e.kind === "funnel_analysis").pop();
  const customTests = events.filter((e) => e.kind === "custom_test");
  const competitiveDiffs = events.filter((e) => e.kind === "competitive_diff");
  const designTheory = events.filter((e) => e.kind === "design_theory").pop();
  const designIssues = events.filter((e) => e.kind === "design_issue");
  const dopamineAnalysis = events.filter((e) => e.kind === "dopamine_analysis").pop();
  const testPlanEv = events.find((e) => e.kind === "test_plan");
  const copySuggestions = events.filter((e) => e.kind === "copy_suggestion");
  const copywritingReport = events.filter((e) => e.kind === "copywriting_report").pop()
    || run?.summary?.copywriting
    || null;
  const demandReport = events.filter((e) => e.kind === "demand_report").pop()
    || run?.summary?.demand_intelligence
    || null;
  const issues = events.filter((e) => e.kind === "issue");
  const benchmarks = events.filter((e) => e.kind === "benchmark");
  const summary = events.find((e) => e.kind === "summary");
  const focusEv = events.find((e) => e.kind === "plan");
  const focusAreas = focusEv?.focus_areas || [];

  // The latest live JPEG frame published by the engine (crawl, fuzz, etc.)
  const liveFrames = events.filter((e) => e.kind === "live_frame");
  const latestFrame = liveFrames[liveFrames.length - 1];
  const routeVideos = events.filter((e) => e.kind === "route_video");

  // Screens discovered by the agentic flow explorer (onboarding → hub → fan-out).
  const screensDiscovered = events.filter((e) => e.kind === "screen_discovered");

  // Per-screen test cases (each carries its own video clip), grouped by screen.
  const screenTestGroups = useMemo(() => {
    const groups = new Map();
    for (const ev of events) {
      if (ev.kind !== "screen_test") continue;
      const key = ev.screen_name || ev.screen_id || "Screen";
      if (!groups.has(key)) {
        groups.set(key, { name: key, purpose: ev.screen_purpose || "", route: ev.route, cases: [] });
      }
      const g = groups.get(key);
      if (ev.screen_purpose && !g.purpose) g.purpose = ev.screen_purpose;
      g.cases.push(ev);
    }
    return Array.from(groups.values());
  }, [events]);

  // Fuzz cases (start + end events keyed by id).
  const fuzzCases = useMemo(() => {
    const m = new Map();
    for (const ev of events) {
      if (ev.kind === "fuzz_case") {
        const prev = m.get(ev.id) || {};
        m.set(ev.id, { ...prev, ...ev });
      }
    }
    return Array.from(m.values());
  }, [events]);

  // Architecture analysis snapshot (last one wins).
  const architecture = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].kind === "architecture") return events[i];
    }
    return null;
  }, [events]);

  // Fold app_graph + page_capture events into a list of discovered pages.
  const appPages = useMemo(() => {
    // Start from the latest app_graph event (it has the canonical page list).
    const graphEv = [...events].reverse().find((e) => e.kind === "app_graph");
    const base = (graphEv?.pages || []).map((p) => ({
      url: p.url, title: p.title, slug: p.slug, captures: {},
    }));
    const byUrl = new Map(base.map((p) => [p.url, p]));
    for (const ev of events) {
      if (ev.kind === "page_capture") {
        let entry = byUrl.get(ev.url);
        if (!entry) {
          entry = { url: ev.url, title: ev.title || "", slug: `page${ev.page_index ?? byUrl.size}`, captures: {} };
          byUrl.set(ev.url, entry);
        }
        entry.captures[ev.viewport] = { ok: ev.ok, url_path: ev.url_path };
        if (ev.title && !entry.title) entry.title = ev.title;
      }
    }
    return Array.from(byUrl.values());
  }, [events]);

  // Fold test_case + test_case_step events into a stateful map.
  const { testCases, stepIndex, activeRunningId } = useMemo(() => {
    const tcs = new Map();
    const steps = {};
    let active = null;
    for (const ev of events) {
      if (ev.kind === "test_case") {
        const existing = tcs.get(ev.id) || {};
        tcs.set(ev.id, { ...existing, ...ev });
        if (ev.status === "running") active = ev.id;
      } else if (ev.kind === "test_case_step") {
        steps[ev.case_id] = ev.step_index;
      }
    }
    return { testCases: Array.from(tcs.values()), stepIndex: steps, activeRunningId: active };
  }, [events]);

  const [activeTab, setActiveTab] = useState(() => searchParams.get("tab") || "live");

  useEffect(() => {
    const t = searchParams.get("tab");
    if (t) setActiveTab(t);
  }, [searchParams]);
  const [selectedCaseId, setSelectedCaseId] = useState(null);
  const [issuePageFilter, setIssuePageFilter] = useState(null);
  const [testingToken, setTestingToken] = useState(false);
  const [tokenTestResult, setTokenTestResult] = useState(null);

  // Auto-switch focus: when test_cases phase begins, prefer that tab; auto-select the running case.
  useEffect(() => {
    if (testCases.length > 0 && activeTab === "live" && !done) {
      setActiveTab("cases");
    }
  }, [testCases.length, activeTab, done]);
  useEffect(() => {
    if (activeRunningId) setSelectedCaseId(activeRunningId);
    else if (!selectedCaseId && testCases.length > 0) setSelectedCaseId(testCases[0].id);
  }, [activeRunningId, testCases, selectedCaseId]);

  const selectedCase = testCases.find((tc) => tc.id === selectedCaseId);

  const latestShot = screenshots[screenshots.length - 1];
  const currentPhase = phases[phases.length - 1];

  const progress = useMemo(() => {
    const total = 13; // github_boot, analyze, explore, per_page, a11y, personas, issues, fuzz, screen_tests, architecture, test_cases, custom_tests, benchmark, report
    const seen = new Set(phases.map((p) => p.phase));
    return Math.min(100, Math.round((seen.size / total) * 100));
  }, [phases]);
