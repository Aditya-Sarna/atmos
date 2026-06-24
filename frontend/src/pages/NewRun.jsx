import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createProject, listCommands, startRun, listProjects, updateProjectGithubToken } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import { ArrowRight, Activity, Sparkles, MousePointerClick, GitCompare, Smartphone, Gauge, Accessibility, Eye, Mic, FileText, Github, Globe } from "lucide-react";

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
  const [source, setSource] = useState("url");        // "url" | "github"
  const [url, setUrl] = useState("");
  const [githubUrl, setGithubUrl] = useState("");
  const [githubToken, setGithubToken] = useState("");
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
          if (found.project.source === "github") {
            setSource("github");
            setGithubUrl(found.project.github_url || found.project.url);
          } else {
            setUrl(found.project.url);
          }
        }
      }).catch(() => {});
    }
  }, [presetProjectId]);

  const submit = async () => {
    if (source === "url" && !url.trim()) {
      toast.error("Please enter a URL to test");
      return;
    }
    if (source === "github" && !githubUrl.trim()) {
      toast.error("Please paste a GitHub repository URL");
      return;
    }
    setBusy(true);
    try {
      let projectId = existingProject?.project_id;
      if (!projectId) {
        const payload = source === "github"
          ? { name: name.trim(), github_url: githubUrl.trim(), github_token: githubToken.trim() || undefined }
          : { name: name.trim(), url: url.trim() };
        const created = await createProject(payload);
        projectId = created.data.project_id;
      } else if (source === "github" && githubToken.trim()) {
        await updateProjectGithubToken(projectId, githubToken.trim());
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
          Paste a URL <em>or</em> connect a GitHub repository. Atmos will detect the archetype, plan the test, and start working live.
        </p>

        <div className="card-elev mt-10 p-6 md:p-8">
          {/* Source selector */}
          {!existingProject && (
            <div className="grid grid-cols-2 gap-2 p-1 rounded-full bg-[#F5F5F7] mb-6 max-w-md" data-testid="source-toggle">
              <button
                type="button"
                onClick={() => setSource("url")}
                className={`rounded-full px-4 py-2 text-sm flex items-center justify-center gap-2 transition ${source === "url" ? "bg-white shadow-sm font-medium" : "text-[#86868B]"}`}
                data-testid="source-url"
              >
                <Globe className="h-4 w-4" /> URL
              </button>
              <button
                type="button"
                onClick={() => setSource("github")}
                className={`rounded-full px-4 py-2 text-sm flex items-center justify-center gap-2 transition ${source === "github" ? "bg-white shadow-sm font-medium" : "text-[#86868B]"}`}
                data-testid="source-github"
              >
                <Github className="h-4 w-4" /> GitHub
              </button>
            </div>
          )}

          <div className="grid md:grid-cols-2 gap-5">
            <div>
              <Label htmlFor="proj-name" className="text-sm">Name</Label>
              <Input
                id="proj-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={source === "github" ? "atmos-billionaire" : "Stripe Checkout"}
                disabled={!!existingProject}
                className="mt-2 h-12 rounded-xl"
                data-testid="project-name-input"
              />
            </div>
            {source === "url" ? (
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
            ) : (
              <div>
                <Label htmlFor="proj-gh" className="text-sm">GitHub repository URL</Label>
                <Input
                  id="proj-gh"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo"
                  disabled={!!existingProject}
                  className="mt-2 h-12 rounded-xl font-mono text-sm"
                  data-testid="project-github-input"
                />
              </div>
            )}
          </div>

          {source === "github" && (
            <div className="mt-5">
              <Label htmlFor="proj-pat" className="text-sm">GitHub Personal Access Token <span className="text-[#86868B]">(optional for public clone, required to open PRs)</span></Label>
              <Input
                id="proj-pat"
                type="password"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                placeholder={existingProject?.has_github_token ? "Saved token on file — enter a new token to replace it" : "ghp_…"}
                autoComplete="new-password"
                className="mt-2 h-12 rounded-xl font-mono text-sm"
                data-testid="project-github-token"
              />
              <div className="mt-2 text-xs text-[#86868B]">
                Scope: <span className="font-mono">repo</span>. Stored separately from the project record and never sent to the LLM. {existingProject?.has_github_token ? "Leave blank to keep the saved token." : "Without it, Atmos can clone public repos but can&apos;t apply PR fixes."}
              </div>
            </div>
          )}

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
              {source === "github"
                ? "Atmos will clone, boot, crawl, fuzz, and score the architecture."
                : "Atmos will crawl, click buttons, fuzz forms, and score the UI."}
            </div>
            <Button
              onClick={submit}
              disabled={busy || (source === "url" ? !url.trim() : !githubUrl.trim())}
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
