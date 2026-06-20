import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createProject, listCommands, startRun, listProjects } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ArrowRight, Activity, Sparkles, MousePointerClick, GitCompare, Smartphone, Gauge, Accessibility, Eye, Mic, FileText } from "lucide-react";

const ICONS = {
  "/atmos analyze": Sparkles, "/atmos explore": MousePointerClick, "/atmos test": Activity,
  "/atmos regress": GitCompare, "/atmos mobile": Smartphone, "/atmos benchmark": Gauge,
  "/atmos accessibility": Accessibility, "/atmos personas": Eye, "/atmos record": Mic, "/atmos report": FileText,
};

export default function NewRun() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const presetProjectId = params.get("project");

  const [commands, setCommands] = useState([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [chosenCmd, setChosenCmd] = useState("/atmos test");
  const [busy, setBusy] = useState(false);
  const [existingProject, setExistingProject] = useState(null);

  useEffect(() => {
    listCommands().then((r) => setCommands(r.data)).catch(() => {});
    if (presetProjectId) {
      listProjects().then((r) => {
        const found = r.data.find((p) => p.project.project_id === presetProjectId);
        if (found) {
          setExistingProject(found.project);
          setName(found.project.name);
          setUrl(found.project.url);
        }
      }).catch(() => {});
    }
  }, [presetProjectId]);

  const submit = async () => {
    if (!url.trim()) {
      toast.error("Please enter a URL to test");
      return;
    }
    setBusy(true);
    try {
      let projectId = existingProject?.project_id;
      if (!projectId) {
        const created = await createProject({ name: name.trim(), url: url.trim() });
        projectId = created.data.project_id;
      }
      const r = await startRun(projectId, chosenCmd);
      toast.success("Atmos is on it.");
      navigate(`/runs/${r.data.run_id}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not start run");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="new-run-page">
      <SiteHeader />
      <main className="max-w-4xl mx-auto px-6 md:px-8 py-12 md:py-16">
        <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">New run</div>
        <h1 className="font-display text-4xl md:text-5xl tracking-tight font-medium">
          What should Atmos look at?
        </h1>
        <p className="mt-3 text-[#1D1D1F]/70 max-w-xl">
          Paste a URL and pick a command. Atmos will detect the archetype, plan the test, and start working live.
        </p>

        <div className="card-elev mt-10 p-6 md:p-8">
          <div className="grid md:grid-cols-2 gap-5">
            <div>
              <Label htmlFor="proj-name" className="text-sm">Name</Label>
              <Input
                id="proj-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Stripe Checkout"
                disabled={!!existingProject}
                className="mt-2 h-12 rounded-xl"
                data-testid="project-name-input"
              />
            </div>
            <div>
              <Label htmlFor="proj-url" className="text-sm">URL</Label>
              <Input
                id="proj-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://yourapp.com"
                disabled={!!existingProject}
                className="mt-2 h-12 rounded-xl font-mono text-sm"
                data-testid="project-url-input"
              />
            </div>
          </div>

          <div className="mt-8">
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Command</div>
            <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2" data-testid="commands-picker">
              {commands.map((c) => {
                const Icon = ICONS[c.cmd] || Activity;
                const active = chosenCmd === c.cmd;
                return (
                  <button
                    key={c.cmd}
                    type="button"
                    onClick={() => setChosenCmd(c.cmd)}
                    className={`text-left rounded-2xl p-4 border transition active:scale-[0.98] ${active ? "border-[#0071E3] bg-white shadow-[0_8px_24px_rgba(0,113,227,0.12)]" : "border-black/10 bg-white hover:border-black/25"}`}
                    data-testid={`cmd-${c.label.toLowerCase()}`}
                  >
                    <Icon className={`h-4 w-4 ${active ? "text-[#0071E3]" : "text-[#1D1D1F]"}`} strokeWidth={1.5} />
                    <div className="mt-3 font-mono text-[11px] text-[#86868B]">{c.cmd}</div>
                    <div className="font-display text-sm font-medium">{c.label}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-10 flex items-center justify-between">
            <div className="text-sm text-[#86868B]">
              Atmos will probe across 8 viewports and 7 personas.
            </div>
            <Button
              onClick={submit}
              disabled={busy || !url.trim()}
              className="rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white h-12 px-6"
              data-testid="start-run-button"
            >
              {busy ? "Starting…" : <>Start run <ArrowRight className="ml-2 h-4 w-4" /></>}
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}
