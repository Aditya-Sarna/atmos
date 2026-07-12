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

        {/* Editor */}
        <section className="card-elev p-6 space-y-4" data-testid="test-case-editor">
          <h2 className="font-medium">{editing ? "Edit test case" : "Write a new test case"}</h2>
          <Input
            placeholder="Test name — e.g. Checkout with empty cart"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Textarea
            placeholder="Description (optional)"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={2}
          />
          <div className="space-y-3">
            <div className="text-[10px] uppercase tracking-widest text-[#86868B]">Steps</div>
            {form.steps.map((step, idx) => (
              <div key={idx} className="flex gap-2 items-start p-3 rounded-xl bg-[#F5F5F7] border border-black/5">
                <GripVertical className="h-4 w-4 mt-2 text-[#86868B] shrink-0" />
                <div className="flex-1 grid grid-cols-1 md:grid-cols-4 gap-2">
                  <Select value={step.action} onValueChange={(v) => updateStep(idx, "action", v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {validActions.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  {step.action === "navigate" && (
                    <Input placeholder="/ or full URL" value={step.url || ""} onChange={(e) => updateStep(idx, "url", e.target.value)} className="md:col-span-2" />
                  )}
                  {(step.action === "click" || step.action === "fill" || step.action === "assert_visible") && (
                    <Input placeholder="CSS selector or text=Button label" value={step.selector || ""} onChange={(e) => updateStep(idx, "selector", e.target.value)} className="md:col-span-2" />
                  )}
                  {step.action === "fill" && (
                    <Input placeholder="Value to type" value={step.value || ""} onChange={(e) => updateStep(idx, "value", e.target.value)} />
                  )}
                  {step.action === "press" && (
                    <Input placeholder="Key — Enter, Tab, Meta+k" value={step.key || ""} onChange={(e) => updateStep(idx, "key", e.target.value)} />
                  )}
                  {step.action === "wait" && (
                    <Input type="number" placeholder="ms" value={step.ms || 1000} onChange={(e) => updateStep(idx, "ms", parseInt(e.target.value, 10))} />
                  )}
                  {step.action === "assert_text" && (
                    <Input placeholder="Text to find on page" value={step.text || ""} onChange={(e) => updateStep(idx, "text", e.target.value)} className="md:col-span-2" />
                  )}
                  <Input placeholder="Step description" value={step.description || ""} onChange={(e) => updateStep(idx, "description", e.target.value)} className="md:col-span-4" />
                </div>
                <Button variant="ghost" size="icon" className="shrink-0" onClick={() => setForm((f) => ({ ...f, steps: f.steps.filter((_, i) => i !== idx) }))}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))}
            <Button variant="outline" className="rounded-full text-sm" onClick={() => setForm((f) => ({ ...f, steps: [...f.steps, { action: "click", selector: "", description: "" }] }))}>
              <Plus className="h-3.5 w-3.5 mr-1" /> Add step
            </Button>
          </div>
          <div className="flex gap-2">
            <Button onClick={saveCase} className="rounded-full bg-[#1D1D1F] text-white">{editing ? "Update" : "Save test case"}</Button>
            {editing && <Button variant="outline" className="rounded-full" onClick={resetForm}>Cancel</Button>}
          </div>
        </section>

        {/* Saved cases */}
        <section className="space-y-3" data-testid="saved-test-cases">
          <h2 className="font-medium">Saved cases ({cases.length})</h2>
          {cases.length === 0 && (
            <p className="text-sm text-[#86868B]">No custom test cases yet. Write steps above — Playwright will execute them and record video during the next run.</p>
          )}
          {cases.map((c) => (
            <div key={c.case_id} className="card-elev p-4 flex items-start justify-between gap-4">
              <div>
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-[#86868B] mt-0.5">{c.steps?.length || 0} steps · {c.enabled !== false ? "Enabled" : "Disabled"}</div>
                <ol className="mt-2 text-sm text-[#1D1D1F]/70 list-decimal list-inside space-y-0.5">
                  {(c.steps || []).slice(0, 4).map((s, i) => (
                    <li key={i}>{s.description || `${s.action} ${s.selector || s.url || ""}`}</li>
                  ))}
                  {(c.steps?.length || 0) > 4 && <li className="text-[#86868B]">+{c.steps.length - 4} more…</li>}
                </ol>
              </div>
              <div className="flex gap-2 shrink-0">
                <Button variant="outline" size="sm" className="rounded-full" onClick={() => { setEditing(c.case_id); setForm({ name: c.name, description: c.description || "", steps: c.steps, enabled: c.enabled !== false }); }}>Edit</Button>
                <Button variant="ghost" size="sm" onClick={async () => {
                  try {
                    await deleteCustomTestCase(projectId, c.case_id);
                    load();
                  } catch (e) {
                    toast.error(e?.response?.data?.detail);
                  }
                }}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </section>
      </main>
    </div>
  );
}
