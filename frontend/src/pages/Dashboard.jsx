import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listProjects } from "@/lib/api";
import SiteHeader from "@/components/SiteHeader";
import AtmosMark from "@/components/AtmosMark";
import { Button } from "@/components/ui/button";
import { Plus, Activity, ArrowUpRight } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

function timeAgo(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

const SCORE_COLOR = (v) => (v >= 80 ? "#34C759" : v >= 70 ? "#FF9500" : "#FF3B30");

function CraftBadge({ craft, gate }) {
  if (!craft?.overall && craft?.overall !== 0) {
    return <span className="text-xs text-[#86868B]">No craft score yet</span>;
  }
  const pass = gate?.passed;
  return (
    <div className="flex items-baseline gap-2" data-testid="craft-badge">
      <span className="font-display text-3xl tabular-nums tracking-tight" style={{ color: SCORE_COLOR(craft.overall) }}>
        {craft.overall}
      </span>
      <span className="text-xs text-[#86868B]">/ 100 · {craft.tier?.replace("_", " ")}</span>
      {gate && (
        <span className={`text-[10px] uppercase tracking-wider ${pass ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
          {pass ? "gate pass" : "gate fail"}
        </span>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const [items, setItems] = useState(null);

  useEffect(() => {
    listProjects().then((r) => setItems(r.data)).catch(() => setItems([]));
  }, []);

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="dashboard-page">
      <SiteHeader />
      <main className="max-w-7xl mx-auto px-6 md:px-8 py-12 md:py-16">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-10">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Craft workspace</div>
            <h1 className="font-display text-4xl md:text-5xl tracking-tight font-medium">
              Hi, {user?.name?.split(" ")[0] || "there"}.
            </h1>
            <p className="mt-3 text-[#1D1D1F]/70 max-w-xl">
              Craft Score is the system of record for product judgment — accessibility, personas, design, funnel, competitive parity, and dark-pattern integrity in one number you can gate on PRs.
            </p>
          </div>
          <Link to="/dashboard/new">
            <Button
              className="rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white h-12 px-6 text-base"
              data-testid="new-run-button"
            >
              <Plus className="mr-2 h-4 w-4" /> New craft run
            </Button>
          </Link>
        </div>

        {items === null && (
          <div className="card-elev p-10 flex items-center justify-center" data-testid="dashboard-loading">
            <AtmosMark size={28} pulse />
          </div>
        )}

        {items && items.length === 0 && (
          <div className="card-elev p-12 text-center" data-testid="empty-state">
            <div className="mx-auto mb-6 w-14 h-14 rounded-2xl bg-[#F5F5F7] flex items-center justify-center">
              <Activity className="h-6 w-6" strokeWidth={1.5} />
            </div>
            <h3 className="font-display text-2xl font-medium">No products yet</h3>
            <p className="mt-2 text-[#1D1D1F]/70 max-w-md mx-auto">
              Add a URL or GitHub repo. Atmos will produce a Craft Score you can trend and gate in CI.
            </p>
            <Link to="/dashboard/new">
              <Button className="mt-6 rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white" data-testid="empty-cta">
                Start your first run
              </Button>
            </Link>
          </div>
        )}

        {items && items.length > 0 && (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="projects-grid">
            {items.map(({ project, last_run }, i) => {
              const craft = project.latest_craft_score || last_run?.summary?.craft_score;
              const gate = project.latest_craft_gate || last_run?.summary?.craft_gate;
              const delta = last_run?.summary?.craft_baseline?.delta;
              return (
                <div
                  key={project.project_id}
                  className="card-elev p-6 hover:border-[#1D1D1F]/20 transition anim-slide-up"
                  style={{ animationDelay: `${i * 40}ms` }}
                  data-testid={`project-card-${project.project_id}`}
                >
                  <Link
                    to={last_run ? `/runs/${last_run.run_id}/report` : `/dashboard/new?project=${project.project_id}`}
                    className="block"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.2em] text-[#86868B]">
                          {project.app_type || "product"}
                        </div>
                        <div className="mt-2 font-display text-xl font-medium">{project.name}</div>
                        <div className="mt-1 text-sm text-[#86868B] truncate max-w-[260px]">
                          {project.url}
                        </div>
                      </div>
                      <ArrowUpRight className="h-4 w-4 text-[#86868B]" />
                    </div>
                    <div className="mt-5">
                      <CraftBadge craft={craft} gate={gate} />
                      {delta != null && (
                        <div className={`mt-1 text-xs ${delta >= 0 ? "text-[#34C759]" : "text-[#FF3B30]"}`}>
                          {delta >= 0 ? "+" : ""}{delta} vs baseline
                        </div>
                      )}
                    </div>
                    <div className="mt-4 flex items-center justify-between text-sm">
                      {last_run ? (
                        <>
                          <span className="font-mono text-xs text-[#1D1D1F]/70">{last_run.command}</span>
                          <span className="flex items-center gap-2">
                            <span className={`w-1.5 h-1.5 rounded-full ${last_run.status === "completed" ? "bg-[#34C759]" : last_run.status === "failed" ? "bg-[#FF3B30]" : "bg-[#FF9500] live-dot"}`} />
                            <span className="text-[#86868B]">{timeAgo(last_run.completed_at || last_run.started_at)}</span>
                          </span>
                        </>
                      ) : (
                        <span className="text-[#86868B]">No runs yet</span>
                      )}
                    </div>
                  </Link>
                  <Link
                    to={`/projects/${project.project_id}/test-plans`}
                    className="mt-2 inline-block text-xs text-[#0071E3] hover:underline mr-3"
                  >
                    Test plan →
                  </Link>
                  <Link
                    to={`/projects/${project.project_id}/test-cases`}
                    className="mt-2 inline-block text-xs text-[#0071E3] hover:underline"
                    data-testid={`project-test-cases-${project.project_id}`}
                  >
                    Custom tests →
                  </Link>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
