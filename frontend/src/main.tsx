import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { demoFetch } from "./mock/api";
import "./App.css";

// In demo mode (no backend), intercept fetch calls with mock data
const originalFetch = window.fetch.bind(window);
window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  if (url.startsWith("/api/")) {
    return demoFetch(input, init);
  }
  return originalFetch(input, init);
}) as typeof window.fetch;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
