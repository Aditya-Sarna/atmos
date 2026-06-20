import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authExchange } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import AtmosMark from "@/components/AtmosMark";

export default function AuthCallback() {
  const hasProcessed = useRef(false);
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [error, setError] = useState(null);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = window.location.hash;
    const match = hash.match(/session_id=([^&]+)/);
    if (!match) {
      navigate("/login", { replace: true });
      return;
    }
    const sessionId = match[1];

    (async () => {
      try {
        const res = await authExchange(sessionId);
        // Clear hash so a refresh doesn't re-exchange
        window.history.replaceState(null, "", window.location.pathname);
        await refresh();
        navigate("/dashboard", { replace: true, state: { user: res.data } });
      } catch (e) {
        setError(e?.response?.data?.detail || "Authentication failed");
      }
    })();
  }, [navigate, refresh]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center" data-testid="auth-callback">
      <AtmosMark size={36} pulse />
      <div className="mt-6 text-sm text-[#86868B]">
        {error ? <span className="text-[#FF3B30]">{error}</span> : "Signing you in…"}
      </div>
    </div>
  );
}
