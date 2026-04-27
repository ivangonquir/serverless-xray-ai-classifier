"use client";

import { useEffect } from "react";

interface ConfirmModalProps {
  open: boolean;
  title: string;          // mono uppercase label, e.g. "CONFIRM LOGOUT"
  message: string;        // body text shown to the user
  confirmLabel?: string;  // defaults to "CONFIRM"
  cancelLabel?: string;   // defaults to "CANCEL"
  variant?: "danger" | "default"; // styles the confirm button
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * ConfirmModal — accessible, themed confirmation dialog.
 *
 * Behavior:
 *   - Renders a full-screen backdrop that dims the page behind it.
 *   - Closes on Escape key.
 *   - Closes on backdrop click (calling onCancel).
 *   - Returns null when `open` is false so it has no DOM cost when hidden.
 */
export default function ConfirmModal({
  open,
  title,
  message,
  confirmLabel = "CONFIRM",
  cancelLabel = "CANCEL",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  const confirmStyles =
    variant === "danger"
      ? "border-signal-red/60 bg-signal-red/10 text-signal-red hover:bg-signal-red/20"
      : "border-cyan/60 bg-cyan/10 text-cyan hover:bg-cyan/20 hover:shadow-glow-cyan";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-abyss/80 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Modal card */}
      <div className="relative w-full max-w-md rounded-2xl border border-steel/60 bg-midnight/95 p-8 shadow-glow-cyan animate-fade-up">
        {/* Corner brackets — match login form aesthetic */}
        <span className="absolute left-3 top-3 h-3 w-3 border-l border-t border-cyan/70" />
        <span className="absolute right-3 top-3 h-3 w-3 border-r border-t border-cyan/70" />
        <span className="absolute bottom-3 left-3 h-3 w-3 border-b border-l border-cyan/70" />
        <span className="absolute bottom-3 right-3 h-3 w-3 border-b border-r border-cyan/70" />

        <div
          id="confirm-modal-title"
          className={`mb-2 font-display text-[10px] tracking-[0.3em] ${
            variant === "danger" ? "text-signal-red" : "text-cyan"
          }`}
        >
          {title}
        </div>
        <p className="mb-8 font-sans text-base text-ice">{message}</p>

        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-steel bg-deepnavy px-5 py-2.5 font-display text-[11px] font-semibold tracking-[0.2em] text-frost transition hover:border-mist hover:text-ice"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            autoFocus
            className={`rounded-lg border px-5 py-2.5 font-display text-[11px] font-semibold tracking-[0.2em] transition ${confirmStyles}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
