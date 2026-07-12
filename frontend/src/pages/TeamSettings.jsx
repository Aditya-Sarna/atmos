import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Shield, UserPlus, Trash2, Check } from "lucide-react";
import { toast } from "sonner";

import SiteHeader from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  getTeam, updateRolePermissions, inviteMember, updateMemberRole, removeMember,
} from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const ROLE_LABELS = {
  admin: "Admin",
  developer: "Developer",
  designer: "Designer",
  viewer: "Viewer",
};

export default function TeamSettings() {
  const { user } = useAuth();
  const [team, setTeam] = useState(null);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("viewer");
  const [selectedRole, setSelectedRole] = useState("developer");
  const [rolePerms, setRolePerms] = useState({});
  const [saving, setSaving] = useState(false);

  const load = () => {
    getTeam()
      .then((r) => {
        setTeam(r.data);
        const map = {};
        for (const role of r.data.roles || []) {
          map[role.role_id] = new Set(role.permissions || []);
        }
        setRolePerms(map);
      })
      .catch((e) => toast.error("Could not load team", { description: e?.response?.data?.detail }))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const canManageRoles = team?.your_permissions?.includes("roles:manage");
  const canManageMembers = team?.your_permissions?.includes("members:write");

  const togglePerm = (roleId, permId) => {
    setRolePerms((prev) => {
      const next = { ...prev };
      const set = new Set(next[roleId] || []);
      if (set.has(permId)) set.delete(permId);
      else set.add(permId);
      next[roleId] = set;
      return next;
    });
  };

  const saveRole = async () => {
    setSaving(true);
    try {
      const perms = [...(rolePerms[selectedRole] || [])];
      await updateRolePermissions(selectedRole, perms);
      toast.success(`Updated ${ROLE_LABELS[selectedRole]} permissions`);
      load();
    } catch (e) {
      toast.error("Save failed", { description: e?.response?.data?.detail });
    } finally {
      setSaving(false);
    }
  };

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    try {
      await inviteMember(inviteEmail.trim(), inviteRole);
      toast.success(`Invited ${inviteEmail}`);
      setInviteEmail("");
      load();
    } catch (e) {
      toast.error("Invite failed", { description: e?.response?.data?.detail });
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F5F5F7]">
        <SiteHeader />
        <div className="max-w-4xl mx-auto px-6 py-20 text-[#86868B]">Loading team…</div>
      </div>
    );
  }

  const catalog = team?.permissions_catalog || [];
  const groups = [...new Set(catalog.map((p) => p.group))];

  return (
    <div className="min-h-screen bg-[#F5F5F7]" data-testid="team-settings-page">
      <SiteHeader />
      <main className="max-w-4xl mx-auto px-6 md:px-8 py-10 space-y-8">
        <div>
          <Link to="/dashboard" className="text-sm text-[#0071E3] hover:underline">← Dashboard</Link>
          <h1 className="font-display text-3xl font-medium mt-2">Team & access control</h1>
          <p className="text-[#86868B] mt-1">
            {team?.org?.name} · You are <span className="font-medium text-[#1D1D1F]">{ROLE_LABELS[team?.your_role] || team?.your_role}</span>
          </p>
        </div>

        {/* Members */}
        <section className="card-elev p-6" data-testid="team-members">
          <div className="flex items-center gap-2 mb-4">
            <Shield className="h-4 w-4 text-[#0071E3]" />
            <h2 className="font-medium">Members</h2>
          </div>
          <div className="space-y-2">
            {(team?.members || []).map((m) => (
              <div key={m.user_id} className="flex items-center justify-between py-2 border-b border-black/5 last:border-0">
                <div>
                  <div className="text-sm font-medium">{m.email}</div>
                  <div className="text-xs text-[#86868B]">{ROLE_LABELS[m.role] || m.role}</div>
                </div>
                {canManageMembers && m.user_id !== user?.user_id && (
                  <div className="flex items-center gap-2">
                    <Select value={m.role} onValueChange={async (v) => {
                      try {
                        await updateMemberRole(m.user_id, v);
                        load();
                      } catch (e) {
                        toast.error(e?.response?.data?.detail);
                      }
                    }}>
                      <SelectTrigger className="w-32 h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {team.builtin_roles.map((r) => (
                          <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={async () => {
                      try {
                        await removeMember(m.user_id);
                        load();
                      } catch (e) {
                        toast.error(e?.response?.data?.detail);
                      }
                    }}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
          {canManageMembers && (
            <div className="flex gap-2 mt-4 pt-4 border-t border-black/5">
              <Input placeholder="email@company.com" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} className="flex-1" />
              <Select value={inviteRole} onValueChange={setInviteRole}>
                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {team?.builtin_roles?.map((r) => (
                    <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button onClick={handleInvite} className="bg-[#0071E3] hover:bg-[#0077ED] text-white rounded-full">
                <UserPlus className="h-4 w-4 mr-1" /> Invite
              </Button>
            </div>
          )}
        </section>

        {/* Role permissions matrix */}
        {canManageRoles && (
          <section className="card-elev p-6" data-testid="role-permissions">
            <h2 className="font-medium mb-1">Customizable permissions</h2>
            <p className="text-sm text-[#86868B] mb-4">Database-style read/write access per role — configured by admin.</p>
            <Select value={selectedRole} onValueChange={setSelectedRole}>
              <SelectTrigger className="w-48 mb-4"><SelectValue /></SelectTrigger>
              <SelectContent>
                {team?.builtin_roles?.filter((r) => r !== "admin").map((r) => (
                  <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="space-y-4">
              {groups.map((group) => (
                <div key={group}>
                  <div className="text-[10px] uppercase tracking-widest text-[#86868B] mb-2">{group}</div>
                  {(catalog.filter((p) => p.group === group)).map((perm) => (
                    <div key={perm.id} className="flex items-center justify-between py-2">
                      <div>
                        <div className="text-sm">{perm.label}</div>
                        <div className="font-mono text-[10px] text-[#86868B]">{perm.id}</div>
                      </div>
                      <Switch
                        checked={(rolePerms[selectedRole] || new Set()).has(perm.id)}
                        onCheckedChange={() => togglePerm(selectedRole, perm.id)}
                        disabled={selectedRole === "admin"}
                      />
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <Button onClick={saveRole} disabled={saving || selectedRole === "admin"} className="mt-4 rounded-full bg-[#1D1D1F] text-white">
              <Check className="h-4 w-4 mr-1" /> Save {ROLE_LABELS[selectedRole]} permissions
            </Button>
          </section>
        )}
      </main>
    </div>
  );
}
