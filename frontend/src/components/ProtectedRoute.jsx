import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import AtmosMark from "@/components/AtmosMark";

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();

  const authBypass =
    process.env.REACT_APP_DISABLE_AUTH === "1" ||
    (typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname));

  if (authBypass) return children;
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" data-testid="protected-loading">
        <AtmosMark size={36} pulse />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}
