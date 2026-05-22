"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "../components/Sidebar";
import ChatInterface from "../components/ChatInterface";
import PatientBar from "../components/PatientBar";
import PatientWorkspace from "../components/PatientWorkspace";
import ConfirmModal from "../components/ConfirmModal";
import { getSession } from "../../lib/auth";

export default function DashboardPage() {
  const router = useRouter();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const [showNewChatConfirm, setShowNewChatConfirm] = useState(false);

  const handleRequestNewChat = () => setShowNewChatConfirm(true);
  const handleConfirmNewChat = () => {
    setShowNewChatConfirm(false);
    setChatKey((k) => k + 1);
  };

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
        selectedPatientId={selectedPatientId}
        onSelectPatient={setSelectedPatientId}
        onRequestNewChat={handleRequestNewChat}
      />

      {/* Middle column: patient context (bar + workspace) */}
      {selectedPatientId && (
        <div className="relative flex w-[940px] shrink-0 flex-col overflow-y-auto border-r border-steel/30 bg-midnight/30">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-radial-glow opacity-40" />
          <div className="relative flex flex-col">
            <PatientBar patientId={selectedPatientId} />
            <PatientWorkspace patientId={selectedPatientId} />
          </div>
        </div>
      )}

      {/* Right column: chat */}
      <main className="relative flex flex-1 flex-col overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-radial-glow opacity-60" />
        <ChatInterface key={chatKey} selectedPatientId={selectedPatientId} />
      </main>

      <ConfirmModal
        open={showNewChatConfirm}
        title="START NEW CONVERSATION"
        message="This will clear the current conversation. Any messages will be lost. Are you sure you want to continue?"
        confirmLabel="START NEW"
        cancelLabel="CANCEL"
        variant="default"
        onConfirm={handleConfirmNewChat}
        onCancel={() => setShowNewChatConfirm(false)}
      />
    </div>
  );
}
