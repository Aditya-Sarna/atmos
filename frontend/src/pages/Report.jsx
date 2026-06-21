import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { getRun } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import AtmosMark from "@/components/AtmosMark";
import IssueDiffCard from "@/components/IssueDiffCard";
import AppGraph from "@/components/AppGraph";
import { TestCaseTheatre, TestCaseList } from "@/components/TestCases";
import { ArrowLeft, FileText, AlertTriangle, Lightbulb, Sparkles } from "lucide-react";

const SEV_COLOR = { critical: "#FF3B30", high: "#FF3B30", medium: "#FF9500", low: "#86868B" };
const SCORE_COLOR = (v) => (v >= 80 ? "#34C759" : v >= 65 ? "#FF9500" : "#FF3B30");

function BigScore({ label, value }) {
  return (
    <div className="card-elev p-6 md:p-8 flex flex-col items-start" data-testid={`big-score-${label.toLowerCase()}`}>
      <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{label}</div>
      <div className="mt-2 font-display text-5xl md:text-6xl tabular-nums tracking-tight" style={{ color: SCORE_COLOR(value) }}>
        {value}
      </div>
      <div className="text-sm text-[#86868B] mt-1">/ 100</div>
    </div>
  );
}

export default function Report() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState(null);
  const [project, setProject] = useState(null);

  useEffect(() => {
    getRun(runId).then((r) => {
      if (!r.data.run?.summary) {
        navigate(`/runs/${runId}`, { replace: true });
        return;
      }
      setRun(r.data.run);
      setProject(r.data.project);
    }).catch(() => navigate("/dashboard", { replace: true }));
  }, [runId, navigate]);

  if (!run) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <AtmosMark size={32} pulse />
      </div>
    );
  }

  const s = run.summary;

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="report-page">
      <SiteHeader />
      <main className="max-w-7xl mx-auto px-6 md:px-8 py-10 md:py-14">
        <Link to={`/runs/${runId}`} className="inline-flex items-center text-sm text-[#86868B] hover:text-[#1D1D1F] mb-6" data-testid="back-to-monitor">
          <ArrowLeft className="h-4 w-4 mr-1" /> Back to live monitor
        </Link>

        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Executive report</div>
            <h1 className="font-display text-4xl md:text-5xl lg:text-6xl tracking-tighter font-medium leading-[1.05]">
              {project?.name}
            </h1>
            <div className="mt-2 text-[#86868B] font-mono text-sm">{run.command} · {project?.url}</div>
          </div>
          <Button
            onClick={() => window.print()}
            variant="outline"
            className="rounded-full"
            data-testid="export-button"
          >
            <FileText className="h-4 w-4 mr-2" /> Export
          </Button>
        </div>

        {/* SCORES */}
        <div className="mt-10 grid md:grid-cols-3 gap-4">
          <BigScore label="Accessibility" value={s.scores?.accessibility ?? 0} />
          <BigScore label="UX" value={s.scores?.ux ?? 0} />
          <BigScore label="Reliability" value={s.scores?.reliability ?? 0} />
        </div>

        {/* COUNTS */}
        <div className="mt-4 card-elev p-6 grid grid-cols-2 md:grid-cols-5 gap-4">
          {Object.entries(s.counts || {}).map(([k, v]) => (
            <div key={k} data-testid={`count-${k}`}>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">{k}</div>
              <div className="font-display text-3xl tabular-nums">{v}</div>
            </div>
          ))}
        </div>

        {/* CRITICAL FINDINGS + RECOMMENDATIONS */}
        <div className="mt-6 grid lg:grid-cols-2 gap-4">
          <div className="card-elev p-6 md:p-8" data-testid="critical-findings">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#86868B] mb-4">
              <AlertTriangle className="h-3.5 w-3.5" strokeWidth={1.75} /> Critical findings
            </div>
            <ul className="space-y-3">
              {(s.critical_findings || []).map((c, i) => (
                <li key={i} className="flex gap-3 text-[#1D1D1F]/90">
                  <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[#FF3B30] shrink-0" />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card-elev p-6 md:p-8" data-testid="recommendations">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#86868B] mb-4">
              <Lightbulb className="h-3.5 w-3.5" strokeWidth={1.75} /> Top recommendations
            </div>
            <ol className="space-y-3 list-decimal pl-5">
              {(s.recommendations || []).map((c, i) => (
                <li key={i} className="text-[#1D1D1F]/90">{c}</li>
              ))}
            </ol>
          </div>
        </div>

        {/* COMPETITIVE INSIGHT */}
        {s.competitive_insight && (
          <div className="mt-6 card-elev p-6 md:p-8 bg-[#1D1D1F] text-white" data-testid="competitive-insight">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40 mb-3">
              <Sparkles className="h-3.5 w-3.5" /> Competitive insight
            </div>
            <p className="font-display text-xl md:text-2xl tracking-tight leading-snug">{s.competitive_insight}</p>
            <div className="mt-4 text-sm text-white/55">Benchmarked against: {(s.benchmarks || []).map((b) => b.competitor).join(" · ")}</div>
          </div>
        )}

        {/* PERSONAS */}
        <div className="mt-6 card-elev p-6 md:p-8" data-testid="report-personas">
          <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-5">Persona scores</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {(s.personas || []).map((p) => (
              <div key={p.id} className="rounded-2xl bg-[#F5F5F7] p-4" data-testid={`persona-score-${p.id}`}>
                <div className="text-sm font-medium">{p.label}</div>
                <div className="text-xs text-[#86868B] mt-0.5 leading-snug">{p.focus}</div>
                <div className="mt-3 flex items-end gap-2">
                  <div className="font-display text-3xl tabular-nums" style={{ color: SCORE_COLOR(p.score) }}>{p.score}</div>
                  <div className="text-xs text-[#A1A1A6] mb-1">/ 100</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* APPLICATION GRAPH */}
        {Array.isArray(s.app_graph) && s.app_graph.length > 0 && (
          <div className="mt-10" data-testid="report-app-graph">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Application graph · pages crawled</div>
            <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
              Atmos analysed {s.app_graph.length} page{s.app_graph.length === 1 ? "" : "s"} across your app.
            </h2>
            <AppGraph pages={s.app_graph} />
          </div>
        )}

        {/* ISSUES with before/after + alternatives */}
        <div className="mt-10 space-y-4" data-testid="report-issues">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Issues · executed fixes · alternatives</div>
              <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium">Atmos found {(s.issues || []).length} issues and shipped a fix for each.</h2>
            </div>
          </div>
          <div className="grid gap-4">
            {(s.issues || []).map((i) => (
              <IssueDiffCard key={i.id} issue={i} />
            ))}
          </div>
        </div>

        {/* TEST CASES with live recording playback */}
        {Array.isArray(s.test_cases) && s.test_cases.length > 0 && (
          <div className="mt-10" data-testid="report-test-cases">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-2">Test cases · recorded</div>
            <h2 className="font-display text-2xl md:text-3xl tracking-tight font-medium mb-5">
              Every case Atmos performed on your UI.
            </h2>
            <ReportTestCases cases={s.test_cases} />
          </div>
        )}

        <div className="mt-10 text-center text-sm text-[#86868B]">Atmos · Generated by Claude Sonnet 4.5 · Executive Report</div>
      </main>
    </div>
  );
}

function ReportTestCases({ cases }) {
  const [selectedId, setSelectedId] = useState(cases[0]?.id || null);
  const selected = cases.find((c) => c.id === selectedId);
  return (
    <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-4">
      <TestCaseList
        cases={cases}
        activeId={selectedId}
        onSelect={setSelectedId}
        currentSteps={Object.fromEntries(cases.map((c) => [c.id, (c.steps?.length || 1) - 1]))}
      />
      <TestCaseTheatre
        testCase={selected}
        currentStep={(selected?.steps?.length || 1) - 1}
      />
    </div>
  );
}
