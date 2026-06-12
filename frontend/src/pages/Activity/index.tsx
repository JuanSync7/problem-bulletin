import { Link, useSearchParams } from "react-router-dom";
import { AgentActivityFeed } from "../Kanban/AgentActivityFeed";
import MentionsTab from "./MentionsTab";
import MineTab from "./MineTab";
import "./Activity.css";

type TabKey = "agent" | "mentions" | "mine";

const TABS: { key: TabKey; label: string }[] = [
  { key: "agent", label: "Agent activity" },
  { key: "mentions", label: "Mentions" },
  { key: "mine", label: "My tickets" },
];

function isValidTab(value: string | null): value is TabKey {
  return value === "agent" || value === "mentions" || value === "mine";
}

export default function ActivityPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab: TabKey = isValidTab(rawTab) ? rawTab : "agent";

  function handleTabClick(key: TabKey) {
    setSearchParams({ tab: key });
  }

  return (
    <div className="activity-page">
      <header className="activity-page__header">
        <h1 className="activity-page__title">Activity</h1>
        <p className="activity-page__subtitle">
          Global activity across the workspace. For your personal inbox,
          visit <Link to="/me">My Space</Link>.
        </p>
      </header>

      <nav className="activity-tabs" aria-label="Activity tabs">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={activeTab === key}
            data-tab={key}
            className={`activity-tab${activeTab === key ? " activity-tab--active" : ""}`}
            onClick={() => handleTabClick(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="activity-panel">
        {activeTab === "agent" && (
          <div data-testid="panel-agent">
            <AgentActivityFeed />
          </div>
        )}
        {activeTab === "mentions" && (
          <div data-testid="panel-mentions" data-tab="mentions">
            <MentionsTab />
          </div>
        )}
        {activeTab === "mine" && (
          <div data-testid="panel-mine" data-tab="mine">
            <MineTab />
          </div>
        )}
      </div>
    </div>
  );
}
