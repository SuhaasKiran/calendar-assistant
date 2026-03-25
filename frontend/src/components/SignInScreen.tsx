import { Navigate } from "react-router-dom";
import { signInUrl } from "../api/auth";
import { useSession } from "../hooks/useSession";

export default function SignInScreen() {
  const { user, loading, oauthBanner, clearOAuthBanner } = useSession();

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="app-shell sign-in">
      <header className="app-header">
        <h1 className="app-title">Calendar Assistant</h1>
        <p className="muted">
          Sign in with your Google Workspace account to manage calendar events and
          email drafts through the assistant.
        </p>
      </header>

      {oauthBanner && (
        <div
          className={`banner ${oauthBanner.startsWith("Sign-in failed") ? "banner-error" : "banner-ok"}`}
          role="status"
        >
          <span>{oauthBanner}</span>
          <button type="button" className="link-btn" onClick={clearOAuthBanner}>
            Dismiss
          </button>
        </div>
      )}

      {loading ? (
        <p className="muted">Checking session…</p>
      ) : (
        <div className="sign-in-actions">
          <a className="btn primary" href={signInUrl()}>
            Continue with Google
          </a>
          <p className="hint muted">
            You will be redirected to Google, then back to this app. The backend
            stores your session in an HTTP-only cookie.
          </p>
        </div>
      )}
    </div>
  );
}
