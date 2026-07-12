import { useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { getRun, applyPatch } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import AtmosMark from "@/components/AtmosMark";
import IssueDiffCard from "@/components/IssueDiffCard";
import AppGraph from "@/components/AppGraph";
import { TestCaseTheatre, TestCaseList } from "@/components/TestCases";
import { ArrowLeft, FileText, AlertTriangle, Lightbulb, Sparkles, Layers, FlaskConical, CheckCircle2, Github } from "lucide-react";
import { toast } from "sonner";

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

        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Craft report</div>
            <h1 className="font-display text-4xl md:text-5xl lg:text-6xl tracking-tighter font-medium leading-[1.05]">
              {project?.name}
            </h1>
            <div className="mt-2 text-[#86868B] font-mono text-sm">{run.command} · {project?.url}</div>
          </div>
          <div className="flex items-start gap-3">
            {s.craft_score?.overall != null && (
              <div className="card-elev p-5 min-w-[180px]" data-testid="craft-score-hero">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">Craft Score</div>
                <div className="mt-1 font-display text-5xl tabular-nums tracking-tight" style={{ color: SCORE_COLOR(s.craft_score.overall) }}>
                  {s.craft_score.overall}
                </div>
                <div className="text-sm text-[#86868B] mt-1">
                  {String(s.craft_score.tier || "").replace("_", " ")} · gate {s.craft_gate?.passed ? "PASS" : "FAIL"}
                </div>
                {s.craft_baseline?.has_baseline && (
                  <div className={`mt-2 text-sm ${(s.craft_baseline.delta ?? 0) >= 0 ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
                    {(s.craft_baseline.delta ?? 0) >= 0 ? "+" : ""}{s.craft_baseline.delta} vs baseline
                  </div>
                )}
              </div>
            )}
            <Button
              onClick={() => window.print()}
              variant="outline"
              className="rounded-full"
              data-testid="export-button"
            >
              <FileText className="h-4 w-4 mr-2" /> Export
            </Button>
          </div>
        </div>

        {project?.source === "github" && (
          <div className="mt-6 card-elev p-4 flex flex-col md:flex-row md:items-center justify-between gap-3" data-testid="github-pr-status">
            <div className="flex items-start gap-3 text-sm text-[#1D1D1F]/80">
              <Github className="h-4 w-4 mt-0.5 text-[#86868B]" />
              <div>
                <div className="font-medium text-[#1D1D1F]">
                  {project?.has_github_token ? "GitHub PRs are enabled for this report." : "GitHub repo connected, but PRs are not enabled yet."}
                </div>
                <div className="text-[#86868B] mt-1">
                  {project?.has_github_token
                    ? "Apply via PR uses the stored project token for this repository."
                    : "Add a GitHub token from New Run to let Atmos open PRs for these fixes."}
                </div>
              </div>
            </div>
            <Link to={`/dashboard/new?project=${project?.project_id || ""}`}>
              <Button variant="outline" className="rounded-full" data-testid="manage-github-token-button">
                {project?.has_github_token ? "Manage token" : "Enable PRs"}
              </Button>
            </Link>
          </div>
        )}

        {s.craft_score?.components && (
          <div className="mt-8 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" data-testid="craft-components">
            {Object.entries(s.craft_score.components).map(([k, v]) => (
              <div key={k} className="rounded-2xl bg-white border border-black/5 p-4">
                <div className="text-[10px] uppercase tracking-[0.15em] text-[#86868B]">{k}</div>
                <div className="font-display text-2xl tabular-nums mt-1" style={{ color: v != null ? SCORE_COLOR(v) : "#86868B" }}>
                  {v ?? "—"}
                </div>
                {s.craft_baseline?.component_deltas?.[k] != null && (
                  <div className="text-[11px] text-[#86868B] mt-1">
                    Δ {s.craft_baseline.component_deltas[k] >= 0 ? "+" : ""}{s.craft_baseline.component_deltas[k]}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* SCORES */}
        <div className="mt-10 grid md:grid-cols-3 gap-4">
          <BigScore label="Accessibility" value={s.scores?.accessibility ?? 0} />
          <BigScore label="UX" value={s.scores?.ux ?? 0} />
          <BigScore label="Reliability" value={s.scores?.reliability ?? 0} />
        </div>

        {/* COUNTS */}
        <div className="mt-4 card-elev p-6 grid grid-cols-2 md:grid-cols-5 gap-4">
