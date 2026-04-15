import React, { useState } from "react";
import { useDarkMode } from "../hooks/useDarkMode";
import { useToast } from "../contexts/ToastContext";
import "./Settings.css";

interface NotificationPrefs {
  emailOnComments: boolean;
  emailOnSolutions: boolean;
  emailOnStatusChanges: boolean;
}

export default function Settings() {
  const { isDark, toggle } = useDarkMode();
  const { show } = useToast();

  const [prefs, setPrefs] = useState<NotificationPrefs>({
    emailOnComments: true,
    emailOnSolutions: true,
    emailOnStatusChanges: true,
  });
  const [isSaving, setIsSaving] = useState(false);

  function handleToggle(key: keyof NotificationPrefs) {
    setPrefs((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSave() {
    setIsSaving(true);
    try {
      const res = await fetch("/api/auth/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          notifications: prefs,
          theme: isDark ? "dark" : "light",
        }),
      });
      if (!res.ok) {
        throw new Error(`Save failed (${res.status})`);
      }
      show("Settings saved successfully", "success");
    } catch (err) {
      show(
        err instanceof Error ? err.message : "Failed to save settings",
        "error"
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="settings">
      <h1 className="settings__title">Settings</h1>

      <div className="settings__section">
        <h2 className="settings__section-title">Notification Preferences</h2>

        <div className="settings__toggle-row">
          <div>
            <div className="settings__toggle-label">Comments</div>
            <div className="settings__toggle-description">
              Email me when someone comments on my problems
            </div>
          </div>
          <label className="settings__switch">
            <input
              type="checkbox"
              checked={prefs.emailOnComments}
              onChange={() => handleToggle("emailOnComments")}
            />
            <span className="settings__switch-track" />
          </label>
        </div>

        <div className="settings__toggle-row">
          <div>
            <div className="settings__toggle-label">Solutions</div>
            <div className="settings__toggle-description">
              Email me when a solution is submitted to my problems
            </div>
          </div>
          <label className="settings__switch">
            <input
              type="checkbox"
              checked={prefs.emailOnSolutions}
              onChange={() => handleToggle("emailOnSolutions")}
            />
            <span className="settings__switch-track" />
          </label>
        </div>

        <div className="settings__toggle-row">
          <div>
            <div className="settings__toggle-label">Status Changes</div>
            <div className="settings__toggle-description">
              Email me when problem status changes
            </div>
          </div>
          <label className="settings__switch">
            <input
              type="checkbox"
              checked={prefs.emailOnStatusChanges}
              onChange={() => handleToggle("emailOnStatusChanges")}
            />
            <span className="settings__switch-track" />
          </label>
        </div>
      </div>

      <div className="settings__section">
        <h2 className="settings__section-title">Appearance</h2>

        <div className="settings__toggle-row">
          <div>
            <div className="settings__toggle-label">Dark Mode</div>
            <div className="settings__toggle-description">
              Toggle between light and dark theme
            </div>
          </div>
          <label className="settings__switch">
            <input
              type="checkbox"
              checked={isDark}
              onChange={toggle}
            />
            <span className="settings__switch-track" />
          </label>
        </div>
      </div>

      <div className="settings__actions">
        <button
          className="settings__save-btn"
          onClick={handleSave}
          disabled={isSaving}
          type="button"
        >
          {isSaving ? "Saving..." : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
