import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Plus, Trash2, Play, GripVertical } from "lucide-react";
import { toast } from "sonner";

import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  getProject, listCustomTestCases, createCustomTestCase, updateCustomTestCase, deleteCustomTestCase, startRun,
} from "@/lib/api";

const ACTIONS = ["navigate", "click", "fill", "press", "wait", "assert_visible", "assert_text", "screenshot"];

const EMPTY_STEP = { action: "navigate", url: "/", description: "Go to home page" };

export default function ProjectTestCases() {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [cases, setCases] = useState([]);
  const [validActions, setValidActions] = useState(ACTIONS);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", description: "", steps: [{ ...EMPTY_STEP }], enabled: true });

  const load = () => {
    Promise.all([
      getProject(projectId),
      listCustomTestCases(projectId),
    ]).then(([projRes, casesRes]) => {
      setProject(projRes.data.project);
      setCases(casesRes.data.cases || []);
      setValidActions(casesRes.data.valid_actions || ACTIONS);
    }).catch((e) => toast.error("Load failed", { description: e?.response?.data?.detail }));
  };

  useEffect(load, [projectId]);

  const resetForm = () => {
    setEditing(null);
    setForm({ name: "", description: "", steps: [{ ...EMPTY_STEP }], enabled: true });
  };

  const saveCase = async () => {
    if (!form.name.trim()) {
      toast.error("Name required");
      return;
    }
    try {
      if (editing) {
        await updateCustomTestCase(projectId, editing, form);
        toast.success("Test case updated");
      } else {
        await createCustomTestCase(projectId, form);
        toast.success("Test case created");
      }
      resetForm();
      load();
    } catch (e) {
      toast.error("Save failed", { description: e?.response?.data?.detail });
    }
  };

  const runWithCases = async () => {
    try {
      const r = await startRun(projectId, "/atmos test");
      window.location.href = `/runs/${r.data.run_id}`;
    } catch (e) {
      toast.error("Could not start run", { description: e?.response?.data?.detail });
    }
  };

  const updateStep = (idx, field, value) => {
    setForm((f) => {
      const steps = [...f.steps];
      steps[idx] = { ...steps[idx], [field]: value };
      return { ...f, steps };
    });
  };

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="custom-test-cases-page">
      <SiteHeader />
      <main className="max-w-5xl mx-auto px-6 md:px-8 py-10 space-y-8">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <Link to="/dashboard" className="text-sm text-[#0071E3] hover:underline">← Dashboard</Link>
            <h1 className="font-display text-3xl font-medium mt-2">Custom test cases</h1>
            <p className="text-[#86868B] mt-1">
              {project?.name} — Playwright records video of each case on the real UI
            </p>
          </div>
          {cases.length > 0 && (
            <Button onClick={runWithCases} className="rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white">
              <Play className="h-4 w-4 mr-1" /> Run all cases
            </Button>
          )}
        </div>
