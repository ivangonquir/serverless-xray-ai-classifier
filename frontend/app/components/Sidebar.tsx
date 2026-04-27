"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LunaMark } from "./LunaMark";
import ConfirmModal from "./ConfirmModal";
import { getSession, logout } from "../../lib/auth";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

/**
 * Left sidebar — Claude-style.
 * Collapsible, shows nav items + user block + logout at the bottom.
 * Icons are placeholders for future feature wiring.
 */
export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const router = useRouter();
  const [username, setUsername] = useState<string>("Clinician");
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Load the username from the session stored at login
  useEffect(() => {
    const session = getSession();
    if (session?.username) setUsername(session.username);
  }, []);

  // Step 1: button click opens the confirmation modal
  const requestLogout = () => setConfirmOpen(true);

  // Step 2: user clicks "LOG OUT" inside the modal
  const confirmLogout = async () => {
    setConfirmOpen(false);
    await logout(); // calls POST /auth/logout and clears localStorage
    router.push("/login");
  };

  return (
    <aside
      className={`relative flex h-screen flex-col border-r border-steel/60 bg-midnight/80 backdrop-blur-xl transition-[width] duration-200 ease-out ${
        collapsed ? "w-[68px]" : "w-[260px]"
      }`}
    >
      {/* Header: toggle + brand */}
      <div className="flex h-16 items-center gap-2 border-b border-steel/40 px-3">
        <button
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-mist transition hover:bg-slate/60 hover:text-cyan"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.8}
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>

        {!collapsed && (
          <div className="flex items-center gap-2">
            <LunaMark size={22} />
            <span className="font-display text-sm font-bold tracking-[0.2em] text-ice">
              LUNA
            </span>
          </div>
        )}
      </div>

      {/* New chat button */}
      <div className="px-3 pt-4">
        <button
          className={`flex w-full items-center gap-3 rounded-md border border-cyan/40 bg-cyan/10 px-3 py-2.5 font-display text-[11px] font-semibold tracking-[0.15em] text-cyan transition hover:bg-cyan/20 hover:shadow-glow-cyan ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <PlusIcon />
          {!collapsed && <span>NEW CHAT</span>}
        </button>
      </div>

      {/* Nav items (placeholders) */}
      <nav className="mt-4 flex-1 space-y-1 overflow-y-auto px-3">
        <NavItem icon={<MessagesIcon />} label="Conversations" collapsed={collapsed} active />
        <NavItem icon={<PatientsIcon />} label="Patients" collapsed={collapsed} />
        <NavItem icon={<DocumentIcon />} label="Reports" collapsed={collapsed} />
        <NavItem icon={<HistoryIcon />} label="History" collapsed={collapsed} />

        {!collapsed && (
          <div className="px-2 pt-6 pb-1 font-display text-[9px] tracking-[0.25em] text-mist/70">
            TOOLS
          </div>
        )}
        <NavItem icon={<SettingsIcon />} label="Settings" collapsed={collapsed} />
        <NavItem icon={<HelpIcon />} label="Help" collapsed={collapsed} />
      </nav>

      {/* Footer: user block + logout */}
      <div className="border-t border-steel/40 p-3">
        <div
          className={`flex items-center gap-3 rounded-md px-2 py-2 ${
            collapsed ? "justify-center" : ""
          }`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-cyan/20 font-display text-[10px] font-bold uppercase text-cyan">
            {username.slice(0, 2)}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate font-sans text-sm text-ice">{username}</div>
              <div className="font-display text-[9px] tracking-[0.2em] text-mist">
                THORACIC · ONCOLOGY
              </div>
            </div>
          )}
        </div>

        <button
          onClick={requestLogout}
          className={`mt-2 flex w-full items-center gap-3 rounded-md px-2 py-2 text-mist transition hover:bg-slate/60 hover:text-signal-red ${
            collapsed ? "justify-center" : ""
          }`}
          title="Log out"
        >
          <LogoutIcon />
          {!collapsed && (
            <span className="font-sans text-sm">Log out</span>
          )}
        </button>
      </div>

      {/* Logout confirmation modal */}
      <ConfirmModal
        open={confirmOpen}
        title="CONFIRM LOGOUT"
        message="Are you sure you want to end your session? You will need to sign in again to continue."
        confirmLabel="LOG OUT"
        cancelLabel="CANCEL"
        variant="danger"
        onConfirm={confirmLogout}
        onCancel={() => setConfirmOpen(false)}
      />
    </aside>
  );
}

/* ---------- Sub-components ---------- */

function NavItem({
  icon,
  label,
  collapsed,
  active,
}: {
  icon: React.ReactNode;
  label: string;
  collapsed: boolean;
  active?: boolean;
}) {
  return (
    <button
      className={`flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm transition ${
        active
          ? "bg-slate/60 text-ice"
          : "text-mist hover:bg-slate/40 hover:text-ice"
      } ${collapsed ? "justify-center" : ""}`}
      title={label}
    >
      <span className="shrink-0">{icon}</span>
      {!collapsed && <span className="truncate font-sans">{label}</span>}
    </button>
  );
}

/* ---------- Icons (inline SVG to avoid extra deps) ---------- */

function PlusIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
    </svg>
  );
}

function MessagesIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.77 9.77 0 01-4-.8L3 20l1-4a7.9 7.9 0 01-1-4c0-4.418 4.03-8 9-8s9 3.582 9 8z"
      />
    </svg>
  );
}

function PatientsIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H2v-2a4 4 0 013-3.87m13-5.13a4 4 0 11-8 0 4 4 0 018 0zM7 10a3 3 0 11-6 0 3 3 0 016 0zm16 0a3 3 0 11-6 0 3 3 0 016 0z"
      />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
      />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  );
}

function SettingsIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
      />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function HelpIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093M12 17h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={1.7}
        d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
      />
    </svg>
  );
}
