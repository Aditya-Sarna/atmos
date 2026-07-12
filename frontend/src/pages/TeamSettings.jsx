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
