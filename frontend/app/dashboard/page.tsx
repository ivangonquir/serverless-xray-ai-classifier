"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "../components/Sidebar";
import ChatInterface from "../components/ChatInterface";
import { getSession } from "../../lib/auth";

export default function DashboardPage() {
  const router = useRouter();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  // Client-side route guard. Real security is enforced by the Lambda Authorizer
  // on the backend — this only avoids rendering the dashboard for users with
  // no session token in localStorage.
  useEffect(() => {
    if (!getSession()) {
      router.replace("/login");
    } else {
      setAuthChecked(true);
    }
  }, [router]);

  if (!authChecked) {
    return (
      <div className="flex h-screen items-center justify-center bg-abyss font-display text-[10px] tracking-[0.3em] text-mist">
        VERIFYING SESSION…
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-abyss">
      {/* Left sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((v) => !v)}
      />

      {/* Main chat area */}
      <main className="relative flex flex-1 flex-col overflow-hidden">
        {/* Ambient top glow */}
        <div className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-radial-glow opacity-60" />

        <div className="relative flex flex-1 flex-col overflow-hidden">
          <ChatInterface />
        </div>
      </main>
    </div>
  );
}
