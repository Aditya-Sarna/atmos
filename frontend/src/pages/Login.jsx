import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import AtmosMark from "@/components/AtmosMark";
import { ShieldCheck, Eye, Sparkles } from "lucide-react";

export default function Login() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!loading && user) navigate("/dashboard", { replace: true });
  }, [user, loading, navigate]);

  const handleSignIn = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen flex" data-testid="login-page">
      {/* LEFT */}
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
              { icon: Sparkles, label: "Claude 4.5" },
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

      {/* RIGHT */}
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
            Sign in with Google to start an autonomous testing run on your product.
          </p>

          <Button
            onClick={handleSignIn}
            size="lg"
            className="mt-8 w-full rounded-full bg-[#1D1D1F] hover:bg-black text-white h-12 text-base"
            data-testid="google-signin-button"
          >
            <svg className="mr-3 h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#fff" d="M21.35 11.1H12v3.2h5.35c-.23 1.2-1.5 3.55-5.35 3.55-3.22 0-5.85-2.67-5.85-5.95s2.63-5.95 5.85-5.95c1.83 0 3.06.78 3.76 1.45l2.56-2.47C16.7 3.5 14.6 2.6 12 2.6 6.92 2.6 2.8 6.72 2.8 11.8s4.12 9.2 9.2 9.2c5.31 0 8.83-3.73 8.83-8.99 0-.6-.06-1.06-.13-1.51z"/>
            </svg>
            Continue with Google
          </Button>

          <p className="mt-5 text-xs text-[#86868B] leading-relaxed">
            By continuing you agree to Atmos&apos;s terms. We only use your email to identify your runs.
          </p>
        </div>
      </div>
    </div>
  );
}
