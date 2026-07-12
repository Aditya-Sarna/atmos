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
