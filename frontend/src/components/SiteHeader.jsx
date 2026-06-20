import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import AtmosMark from "@/components/AtmosMark";
import { Button } from "@/components/ui/button";

export default function SiteHeader({ variant = "marketing" }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <header className="sticky top-0 z-40 glass" data-testid="site-header">
      <div className="max-w-7xl mx-auto px-6 md:px-8 h-16 flex items-center justify-between">
        <Link to="/" className="flex items-center" data-testid="brand-home-link">
          <AtmosMark size={30} />
        </Link>

        <nav className="hidden md:flex items-center gap-8 text-sm text-[#1D1D1F]/80">
          <a href="/#commands" className="hover:text-[#1D1D1F]" data-testid="nav-commands">Commands</a>
          <a href="/#personas" className="hover:text-[#1D1D1F]" data-testid="nav-personas">Personas</a>
          <a href="/#benchmarks" className="hover:text-[#1D1D1F]" data-testid="nav-benchmarks">Benchmarks</a>
          <a href="/#how" className="hover:text-[#1D1D1F]" data-testid="nav-how">How it works</a>
        </nav>

        <div className="flex items-center gap-3">
          {user ? (
            <>
              <Link to="/dashboard">
                <Button variant="ghost" className="rounded-full" data-testid="header-dashboard-btn">
                  Dashboard
                </Button>
              </Link>
              <Button
                variant="outline"
                className="rounded-full"
                onClick={async () => { await logout(); navigate("/"); }}
                data-testid="header-logout-btn"
              >
                Sign out
              </Button>
            </>
          ) : (
            <>
              {variant === "marketing" && (
                <Link to="/login">
                  <Button variant="ghost" className="rounded-full" data-testid="header-signin-btn">
                    Sign in
                  </Button>
                </Link>
              )}
              <Link to="/login">
                <Button className="rounded-full bg-[#0071E3] hover:bg-[#0077ED] text-white" data-testid="header-cta-btn">
                  Get started
                </Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
