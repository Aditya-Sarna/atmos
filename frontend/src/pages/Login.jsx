import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { authLogin, authRegister } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import AtmosMark from "@/components/AtmosMark";
import { ShieldCheck, Eye, Sparkles } from "lucide-react";
import { toast } from "sonner";

export default function Login() {
  const { user, loading, refresh } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login"); // login | register
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) navigate("/dashboard", { replace: true });
  }, [user, loading, navigate]);

  const handleLocalAuth = async (e) => {
    e.preventDefault();
    if (!email.trim() || password.length < 8) {
      toast.error("Use a valid email and password (8+ characters)");
      return;
    }
    setBusy(true);
    try {
      if (mode === "register") {
        await authRegister({ email: email.trim(), password, name: name.trim() || undefined });
        toast.success("Account created");
      } else {
        await authLogin({ email: email.trim(), password });
        toast.success("Signed in");
      }
      if (refresh) await refresh();
      navigate("/dashboard", { replace: true });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Could not sign in");
    } finally {
      setBusy(false);
    }
  };

  const handleGoogle = () => {
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen flex" data-testid="login-page">
      <div className="hidden lg:flex flex-col justify-between p-12 w-1/2 bg-[#1D1D1F] text-white relative overflow-hidden">
        <div className="absolute inset-0 opacity-[0.06] dot-grid" />
        <div className="relative">
          <AtmosMark size={32} className="text-white [&_*]:fill-white" />
        </div>
        <div className="relative max-w-md">
          <h2 className="font-display text-4xl tracking-tight font-medium leading-tight">
            &ldquo;Atmos found seven WCAG violations in our checkout in under three minutes.&rdquo;
          </h2>
          <div className="mt-6 text-sm text-white/55">Engineering lead — design-led SaaS</div>

          <div className="mt-10 grid grid-cols-3 gap-3">
            {[
              { icon: Eye, label: "7 personas" },
              { icon: ShieldCheck, label: "WCAG aware" },
              { icon: Sparkles, label: "IDE-native LLM" },
            ].map((b) => (
              <div key={b.label} className="rounded-xl border border-white/15 p-3">
                <b.icon className="h-4 w-4 text-white/70" strokeWidth={1.5} />
                <div className="mt-2 text-xs text-white/65">{b.label}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="relative text-xs text-white/40">© Atmos</div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <div className="lg:hidden mb-10">
            <AtmosMark size={28} />
          </div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#86868B] mb-3">Sign in</div>
          <h1 className="font-display text-4xl tracking-tight font-medium">
            Welcome to <span className="text-[#86868B]">Atmos.</span>
          </h1>
          <p className="mt-3 text-[#1D1D1F]/70">
            Create an account or sign in — then start an autonomous craft run on your product.
          </p>

          <div className="mt-6 grid grid-cols-2 gap-1 p-1 rounded-full bg-[#F5F5F7]" data-testid="auth-mode-toggle">
