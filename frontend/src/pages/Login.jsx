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
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`rounded-full py-2 text-sm transition ${mode === "login" ? "bg-white shadow-sm font-medium" : "text-[#86868B]"}`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`rounded-full py-2 text-sm transition ${mode === "register" ? "bg-white shadow-sm font-medium" : "text-[#86868B]"}`}
            >
              Create account
            </button>
          </div>

          <form className="mt-6 space-y-4" onSubmit={handleLocalAuth} data-testid="local-auth-form">
            {mode === "register" && (
              <div>
                <Label htmlFor="auth-name">Name</Label>
                <Input
                  id="auth-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="mt-2 h-12 rounded-xl"
                  placeholder="Alex"
                  data-testid="login-name-input"
                />
              </div>
            )}
            <div>
              <Label htmlFor="auth-email">Email</Label>
              <Input
                id="auth-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-2 h-12 rounded-xl"
                placeholder="you@company.com"
                required
                data-testid="login-email-input"
              />
            </div>
            <div>
              <Label htmlFor="auth-password">Password</Label>
              <Input
                id="auth-password"
                type="password"
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-2 h-12 rounded-xl"
                placeholder="8+ characters"
                minLength={8}
                required
                data-testid="login-password-input"
              />
            </div>
            <Button
              type="submit"
              disabled={busy}
              size="lg"
              className="w-full rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white h-12 text-base"
              data-testid="login-submit-button"
            >
              {busy ? "Working…" : mode === "register" ? "Create account" : "Sign in"}
            </Button>
          </form>

          <div className="my-6 flex items-center gap-3 text-xs text-[#86868B]">
            <div className="flex-1 h-px bg-black/10" />
            or
            <div className="flex-1 h-px bg-black/10" />
          </div>

          <Button
            onClick={handleGoogle}
            size="lg"
            variant="outline"
            className="w-full rounded-full h-12 text-base border-black/15"
            data-testid="google-signin-button"
          >
            <svg className="mr-3 h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#1D1D1F" d="M21.35 11.1H12v3.2h5.35c-.23 1.2-1.5 3.55-5.35 3.55-3.22 0-5.85-2.67-5.85-5.95s2.63-5.95 5.85-5.95c1.83 0 3.06.78 3.76 1.45l2.56-2.47C16.7 3.5 14.6 2.6 12 2.6 6.92 2.6 2.8 6.72 2.8 11.8s4.12 9.2 9.2 9.2c5.31 0 8.83-3.73 8.83-8.99 0-.6-.06-1.06-.13-1.51z"/>
            </svg>
            Continue with Google
          </Button>

          <p className="mt-5 text-xs text-[#86868B] leading-relaxed">
            By continuing you agree to Atmos&apos;s terms. Email/password works without Emergent; Google uses Emergent OAuth when available.
          </p>
        </div>
      </div>
    </div>
  );
}
