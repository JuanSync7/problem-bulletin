import React, { useState, useCallback } from "react";
import { Sidebar } from "./Sidebar";
import { useMediaQuery } from "../hooks/useMediaQuery";

interface MainLayoutProps {
  children: React.ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const openSidebar = useCallback(() => setSidebarOpen(true), []);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  return (
    <div className="layout">
      {/* Mobile hamburger button */}
      {!isDesktop && (
        <header className="layout__mobile-header">
          <button
            className="layout__hamburger"
            onClick={openSidebar}
            aria-label="Open navigation"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 12h18M3 6h18M3 18h18" />
            </svg>
          </button>
          <span className="layout__mobile-title">Aion Bulletin</span>
        </header>
      )}

      <Sidebar isOpen={isDesktop || sidebarOpen} onClose={closeSidebar} />

      <main className="layout__content">{children}</main>
    </div>
  );
}
