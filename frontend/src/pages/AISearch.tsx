import React from "react";
import "./Search.css";

export default function AISearch() {
  return (
    <div className="search-page">
      <div className="search-page__header">
        <h1 className="search-page__title">AI Search</h1>
        <div className="search-page__input-wrapper">
          <svg
            className="search-page__icon"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            className="search-page__input"
            type="text"
            placeholder="AI-powered search coming soon..."
            disabled
            style={{ opacity: 0.5, cursor: "not-allowed" }}
          />
        </div>
      </div>

      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          marginBottom: "2rem",
          opacity: 0.5,
        }}
      >
        <button
          className="leaderboard__filter-btn"
          disabled
          type="button"
          style={{ cursor: "not-allowed", opacity: 0.5 }}
        >
          Semantic
        </button>
        <button
          className="leaderboard__filter-btn"
          disabled
          type="button"
          style={{ cursor: "not-allowed", opacity: 0.5 }}
        >
          Similar Problems
        </button>
        <button
          className="leaderboard__filter-btn"
          disabled
          type="button"
          style={{ cursor: "not-allowed", opacity: 0.5 }}
        >
          By Solution Type
        </button>
      </div>

      <div className="ai-search__coming-soon">
        <div className="ai-search__badge">Powered by AI</div>
        <h2 className="ai-search__heading">Coming Soon</h2>
        <p className="ai-search__description">
          AI-powered search will let you find problems using natural language
          queries, discover similar issues, and get intelligent recommendations
          based on your interests and expertise.
        </p>
      </div>
    </div>
  );
}
