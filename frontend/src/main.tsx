import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { demoFetch } from "./mock/api";
import "./App.css";

// Replace fetch globally — demoFetch passes through to real fetch
// when the backend is available, and returns mock data when it's not.
// In dev (vite serve), always passthrough to the real backend; the mock
// layer is for the static GitHub Pages build only.
if (!import.meta.env.DEV) {
  window.fetch = demoFetch as typeof window.fetch;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
