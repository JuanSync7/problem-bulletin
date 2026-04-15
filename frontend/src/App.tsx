import React, { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./theme";
import { ToastProvider } from "./contexts/ToastContext";
import { MainLayout } from "./layouts/MainLayout";

const Landing = lazy(() => import("./pages/Landing"));
const Problems = lazy(() => import("./pages/Feed"));
const ProblemDetail = lazy(() => import("./pages/ProblemDetail"));
const Submit = lazy(() => import("./pages/Submit"));
const Search = lazy(() => import("./pages/Search"));
const AiSearch = lazy(() => import("./pages/AISearch"));
const Leaderboard = lazy(() => import("./pages/Leaderboard"));
const Settings = lazy(() => import("./pages/Settings"));
const AdminDashboard = lazy(() => import("./pages/admin/Dashboard"));
const AdminCategories = lazy(() => import("./pages/admin/Categories"));
const AdminTags = lazy(() => import("./pages/admin/Tags"));
const AdminUsers = lazy(() => import("./pages/admin/Users"));
const AdminModeration = lazy(() => import("./pages/admin/Moderation"));
const NotFound = lazy(() => import("./pages/NotFound"));

function AppFallback() {
  return (
    <div className="app-loading">
      <div className="app-loading__spinner" />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <ToastProvider>
        <MainLayout>
          <Suspense fallback={<AppFallback />}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/problems" element={<Problems />} />
              <Route path="/problems/:id" element={<ProblemDetail />} />
              <Route path="/submit" element={<Submit />} />
              <Route path="/search" element={<Search />} />
              <Route path="/ai-search" element={<AiSearch />} />
              <Route path="/leaderboard" element={<Leaderboard />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/admin" element={<AdminDashboard />} />
              <Route path="/admin/categories" element={<AdminCategories />} />
              <Route path="/admin/tags" element={<AdminTags />} />
              <Route path="/admin/users" element={<AdminUsers />} />
              <Route path="/admin/moderation" element={<AdminModeration />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </MainLayout>
        </ToastProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
