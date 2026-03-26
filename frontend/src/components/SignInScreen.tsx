import { Navigate } from "react-router-dom";
import { signInUrl } from "../api/auth";
import { useAssistantName, useAssistantTagline } from "../hooks/useAssistantName";
import { useSession } from "../hooks/useSession";

export default function SignInScreen() {
  const { user, loading, oauthBanner, clearOAuthBanner } = useSession();
  const assistantName = useAssistantName();
  const assistantTagline = useAssistantTagline();

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="app-shell sign-in">
      <section className="sign-in-card" aria-label="Sign in">
        <header className="app-header sign-in-header">
          <h1 className="app-title">{assistantName}</h1>
          <p className="sign-in-tagline">{assistantTagline}</p>
          <p className="muted sign-in-description">
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
          <p className="muted sign-in-status">Checking session…</p>
        ) : (
          <div className="sign-in-actions">
            <a className="btn primary" href={signInUrl()}>
              Sign In with Google
            </a>
            {/* <p className="hint muted">
              You will be redirected to Google, then back to this app. The backend
              stores your session in an HTTP-only cookie.
            </p> */}
          </div>
        )}
      </section>
    </div>
  );
}
