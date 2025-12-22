import React from "react";
import "../styles/SessionExpiredPrompt.css";

export default function SessionExpiredPrompt() {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const h = () => setOpen(true);
    window.addEventListener("session-expired", h);
    return () => window.removeEventListener("session-expired", h);
  }, []);

  if (!open) return null;

  const goToLogin = () => {
    const next = encodeURIComponent(sessionStorage.getItem("next") || "/");
    // Optionally: call /logout to clear server-side session
    // fetch("/auth/logout", { method: "POST", credentials: "include" }).finally(() => {
    window.location.href = `/login?reason=expired&next=${next}`;
    // });
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-expired-title"
      className="sep-backdrop"
      onClick={goToLogin} // click outside goes to login
    >
      <div
        className="sep-modal"
        onClick={(e) => e.stopPropagation()} // keep clicks inside from closing
      >
        <h3 id="session-expired-title">Session expired</h3>
        <p>Your login session ended. Please sign in again to continue.</p>
        <div className="sep-actions">
          <button className="sep-primary" onClick={goToLogin}>
            Go to login
          </button>
        </div>
      </div>
    </div>
  );
}
