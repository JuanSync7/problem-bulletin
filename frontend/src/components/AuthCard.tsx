import React, { useState } from "react";

interface AuthCardProps {
  isLoading: boolean;
  error: string | null;
  isDemo?: boolean;
  onMicrosoftLogin: () => void;
  onMagicLink: (email: string) => Promise<boolean>;
  onClearError: () => void;
}

type Tab = "microsoft" | "magic";

export function AuthCard({
  isLoading,
  error,
  isDemo = false,
  onMicrosoftLogin,
  onMagicLink,
  onClearError,
}: AuthCardProps) {
  const [activeTab, setActiveTab] = useState<Tab>("microsoft");
  const [email, setEmail] = useState("");
  const [magicSent, setMagicSent] = useState(false);

  function handleTabChange(tab: Tab) {
    setActiveTab(tab);
    setMagicSent(false);
    onClearError();
  }

  async function handleMagicSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    const success = await onMagicLink(email.trim());
    if (success) {
      setMagicSent(true);
    }
  }

  return (
    <div className="auth-card">
      <div className="auth-card__inner">
        <h2 className="auth-card__title">Welcome to Aion Bulletin</h2>

        <div className="auth-card__tabs">
          <button
            type="button"
            className={`auth-card__tab ${activeTab === "microsoft" ? "auth-card__tab--active" : ""}`}
            onClick={() => handleTabChange("microsoft")}
          >
            Microsoft
          </button>
          <button
            type="button"
            className={`auth-card__tab ${activeTab === "magic" ? "auth-card__tab--active" : ""}`}
            onClick={() => handleTabChange("magic")}
          >
            Magic Link
          </button>
        </div>

        <div className="auth-card__body">
          {activeTab === "microsoft" && (
            <button
              type="button"
              className="auth-card__ms-btn"
              onClick={onMicrosoftLogin}
              disabled={isLoading || isDemo}
            >
              {isLoading ? (
                <span className="auth-card__spinner" />
              ) : (
                <svg
                  className="auth-card__ms-icon"
                  viewBox="0 0 21 21"
                  width="21"
                  height="21"
                  aria-hidden="true"
                >
                  <rect x="1" y="1" width="9" height="9" fill="#F25022" />
                  <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
                  <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
                  <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
                </svg>
              )}
              Sign in with Microsoft
            </button>
          )}

          {activeTab === "magic" && (
            <>
              {magicSent ? (
                <p className="auth-card__sent-msg">
                  Check your inbox for a sign-in link. You can close this tab.
                </p>
              ) : (
                <form className="auth-card__magic-form" onSubmit={handleMagicSubmit}>
                  <label className="auth-card__label" htmlFor="magic-email">
                    Email address
                  </label>
                  <input
                    id="magic-email"
                    className="auth-card__input"
                    type="email"
                    required
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    disabled={isLoading || isDemo}
                    autoComplete="email"
                  />
                  <button
                    type="submit"
                    className="auth-card__submit-btn"
                    disabled={isLoading || isDemo || !email.trim()}
                  >
                    {isLoading ? <span className="auth-card__spinner" /> : null}
                    Send Magic Link
                  </button>
                </form>
              )}
            </>
          )}
        </div>

        {error && <p className="auth-card__error">{error}</p>}
      </div>
    </div>
  );
}
