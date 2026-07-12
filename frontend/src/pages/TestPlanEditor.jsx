import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Play, Plus, Trash2, GripVertical, Sparkles, Zap } from "lucide-react";
import { toast } from "sonner";

import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  generateTestPlan, updateTestPlan, getTestPlan, startRun, getProject,
  updateProjectSettings, listDesignThemes,
} from "@/lib/api";

export default function TestPlanEditor() {
  const { projectId, planId: routePlanId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [plan, setPlan] = useState(null);
  const [themes, setThemes] = useState([]);
  const [command, setCommand] = useState("/atmos test");
  const [dopamine, setDopamine] = useState(false);
  const [designTheme, setDesignTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    getProject(projectId).then((r) => {
      setProject(r.data.project);
      setDopamine(!!r.data.project?.enable_dopamine_max);
      setDesignTheme(r.data.project?.design_theme || "");
    }).catch(() => {});
    listDesignThemes().then((r) => setThemes(Object.entries(r.data.themes || {}))).catch(() => {});
    if (routePlanId) {
      getTestPlan(projectId, routePlanId).then((r) => setPlan(r.data)).catch(() => {});
    }
  }, [projectId, routePlanId]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const r = await generateTestPlan(projectId, { command, page_url: project?.url });
      setPlan(r.data);
      toast.success("Test plan generated — review and edit before running");
      navigate(`/projects/${projectId}/test-plans/${r.data.plan_id}`, { replace: true });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not generate plan");
    } finally {
      setGenerating(false);
    }
  };

  const savePlan = async () => {
    if (!plan?.plan_id) return;
    setBusy(true);
    try {
      const r = await updateTestPlan(projectId, plan.plan_id, {
        narrative: plan.narrative,
        focus_areas: plan.focus_areas,
        test_cases: plan.test_cases,
        status: "approved",
      });
      setPlan(r.data);
      await updateProjectSettings(projectId, {
        enable_dopamine_max: dopamine,
        design_theme: designTheme || undefined,
      });
      toast.success("Plan saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const runPlan = async () => {
    if (!plan?.plan_id) return;
    setBusy(true);
    try {
      await savePlan();
      const r = await startRun(projectId, {
        command,
        plan_id: plan.plan_id,
        enable_dopamine_max: dopamine,
        design_theme_override: designTheme || undefined,
      });
      toast.success("Run started with your approved plan");
      navigate(`/runs/${r.data.run_id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not start run");
    } finally {
      setBusy(false);
    }
  };

  const updateCase = (idx, field, value) => {
    setPlan((p) => {
      const cases = [...(p.test_cases || [])];
      cases[idx] = { ...cases[idx], [field]: value };
      return { ...p, test_cases: cases };
    });
  };

  const addCase = () => {
    setPlan((p) => ({
      ...p,
      test_cases: [
        ...(p?.test_cases || []),
        { id: `tp_${Date.now()}`, name: "New test case", category: "UX", enabled: true, steps: ["Step 1"], rationale: "" },
      ],
    }));
  };

  if (!project) {
    return (
      <div className="min-h-screen bg-[#F5F5F7]">
        <SiteHeader />
        <div className="p-12 text-[#86868B]">Loading…</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="test-plan-editor">
      <SiteHeader />
      <main className="max-w-4xl mx-auto px-6 md:px-8 py-10 space-y-8">
        <div>
          <Link to="/dashboard" className="text-sm text-[#0071E3] hover:underline">← Dashboard</Link>
          <h1 className="font-display text-3xl font-medium mt-2">AI test plan editor</h1>
          <p className="text-[#86868B] mt-1">{project.name} — review plan before Atmos runs</p>
        </div>

        {!plan && (
          <section className="card-elev p-8 text-center">
            <Sparkles className="h-10 w-10 mx-auto text-[#0071E3] mb-4" />
            <h2 className="font-medium text-lg">Generate a test plan first</h2>
            <p className="text-sm text-[#86868B] mt-2 max-w-md mx-auto">
              Uses your IDE LLM when configured — sync codebase from VS Code/Cursor extension for best results.
            </p>
            <Button onClick={handleGenerate} disabled={generating} className="mt-6 rounded-full bg-[#0071E3] text-white">
              {generating ? "Generating…" : "Generate test plan"}
            </Button>
          </section>
        )}

        {plan && (
          <>
            <section className="card-elev p-6 space-y-4">
              <Textarea
                value={plan.narrative || ""}
                onChange={(e) => setPlan({ ...plan, narrative: e.target.value })}
                rows={2}
                placeholder="Plan narrative"
              />
              <div className="flex flex-wrap gap-2">
                {(plan.focus_areas || []).map((a, i) => (
                  <span key={i} className="text-xs px-2 py-1 rounded-full bg-[#F5F5F7] border border-black/5">{a}</span>
                ))}
              </div>
            </section>

            <section className="card-elev p-6 space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-medium">Test cases ({plan.test_cases?.length || 0})</h2>
