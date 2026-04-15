import React from "react";

export function PlaceholderPage({ name }: { name: string }) {
  return (
    <div className="page-placeholder">
      <h1>{name}</h1>
      <p>This page is under construction.</p>
    </div>
  );
}

export const Home = () => <PlaceholderPage name="Home" />;
export const Problems = () => <PlaceholderPage name="Problems" />;
export const ProblemDetail = () => <PlaceholderPage name="Problem Detail" />;
export const Submit = () => <PlaceholderPage name="Submit" />;
export const Search = () => <PlaceholderPage name="Search" />;
export const AiSearch = () => <PlaceholderPage name="AI Search" />;
export const Leaderboard = () => <PlaceholderPage name="Leaderboard" />;
export const Settings = () => <PlaceholderPage name="Settings" />;
export const AdminUsers = () => <PlaceholderPage name="Admin: Users" />;
export const AdminModeration = () => <PlaceholderPage name="Admin: Moderation" />;
export const AdminConfig = () => <PlaceholderPage name="Admin: Config" />;
export const NotFound = () => <PlaceholderPage name="404 — Page Not Found" />;
