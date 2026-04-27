"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LunaMark } from "../components/LunaMark";
import { login } from "../../lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      // Calls POST /auth/login on the backend, stores session token in localStorage
      await login(userId.trim(), password);
      router.push("/dashboard");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unable to sign in. Please try again.";
      setError(message);
      setLoading(false);
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-abyss">
      {/* Ambient radial glow */}
      <div className="pointer-events-none absolute inset-0 bg-radial-glow" />

      {/* Faint grid background */}
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "linear-gradient(rgba(168,180,206,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(168,180,206,0.04) 1px, transparent 1px)",
          backgroundSize: "48px 48px",
        }}
      />

      {/* Decorative orbit ring, top-right */}
      <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full border border-cyan/10" />
      <div className="pointer-events-none absolute -right-24 -top-24 h-[380px] w-[380px] rounded-full border border-cyan/5" />

      <div className="relative z-10 mx-auto flex min-h-screen max-w-7xl items-center justify-between px-8 py-12">
        {/* LEFT: Brand panel */}
        <section className="hidden flex-1 flex-col justify-between pr-16 lg:flex">
          <div className="flex items-center gap-3">
            <LunaMark size={40} />
            <div>
              <div className="font-display text-2xl font-bold tracking-[0.25em] text-ice">
                LUNA
              </div>
              <div className="font-display text-[10px] tracking-[0.4em] text-cyan">
                LUNG KNOWLEDGE ASSISTANT
              </div>
            </div>
          </div>

          <div className="max-w-lg space-y-8">
            <div className="space-y-1">
              <div className="font-display text-[10px] tracking-[0.3em] text-mist">
                CLINICAL DECISION SUPPORT SYSTEM
              </div>
              <div className="h-px w-12 bg-cyan/60" />
            </div>
            <h1 className="font-sans text-5xl font-light leading-[1.1] text-ice whitespace-nowrap">
              <span className="font-semibold text-cyan">Intelligent</span> Lung Cancer Screening
            </h1>
            <p className="text-frost">
              Welcome to LUNA: Empowering clinical decisions with multimodal
              AI insights and evidence-based screening for lung cancer.
            </p>
          </div>

          <footer className="flex items-center gap-6 font-display text-[10px] tracking-[0.25em] text-mist">
            <span>v0.1.0 · PROOF OF CONCEPT</span>
            <span className="h-1 w-1 rounded-full bg-mist/40" />
            <span>AWS SERVERLESS</span>
            <span className="h-1 w-1 rounded-full bg-mist/40" />
            <span>HIPAA-ALIGNED</span>
          </footer>
        </section>

        {/* RIGHT: Form panel */}
        <section className="w-full max-w-md">
          <div className="relative rounded-2xl border border-steel/60 bg-midnight/80 p-10 shadow-glow-cyan backdrop-blur-xl">
            {/* Corner brackets for technical feel */}
            <span className="absolute left-3 top-3 h-3 w-3 border-l border-t border-cyan/70" />
            <span className="absolute right-3 top-3 h-3 w-3 border-r border-t border-cyan/70" />
            <span className="absolute bottom-3 left-3 h-3 w-3 border-b border-l border-cyan/70" />
            <span className="absolute bottom-3 right-3 h-3 w-3 border-b border-r border-cyan/70" />

            {/* Mobile brand header */}
            <div className="mb-8 flex items-center gap-2.5 lg:hidden">
              <LunaMark size={28} />
              <span className="font-display text-lg font-bold tracking-[0.2em]">
                LUNA
              </span>
            </div>

            <header className="mb-8">
              <div className="mb-2 font-display text-[10px] tracking-[0.3em] text-cyan">
                SECURE ACCESS
              </div>
              <h2 className="font-sans text-2xl font-medium text-ice">
                Clinician sign-in
              </h2>
              <p className="mt-2 text-sm text-frost">
                Authenticate to access the diagnostic workspace.
              </p>
            </header>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="userId"
                  className="mb-2 block font-display text-[10px] tracking-[0.25em] text-mist"
                >
                  USER ID
                </label>
                <input
                  id="userId"
                  type="text"
                  autoComplete="username"
                  required
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  className="w-full rounded-lg border border-steel bg-deepnavy px-4 py-3 font-sans text-ice placeholder-mist/60 outline-none transition focus:border-cyan focus:shadow-glow-cyan"
                  placeholder="e.g. dr.smith"
                />
              </div>

              <div>
                <label
                  htmlFor="password"
                  className="mb-2 block font-display text-[10px] tracking-[0.25em] text-mist"
                >
                  PASSWORD
                </label>
                <input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-steel bg-deepnavy px-4 py-3 font-sans text-ice placeholder-mist/60 outline-none transition focus:border-cyan focus:shadow-glow-cyan"
                  placeholder="••••••••"
                />
              </div>

              <div className="flex items-center justify-between pt-1">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-frost">
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 accent-cyan"
                  />
                  Remember session
                </label>
                <a
                  href="#"
                  className="text-sm text-cyan transition hover:text-cyan-glow"
                >
                  Forgot password
                </a>
              </div>

              {error && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-md border border-signal-red/40 bg-signal-red/10 px-3 py-2.5 text-sm text-signal-red"
                >
                  <svg
                    className="mt-0.5 h-4 w-4 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <span>{error}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="group relative mt-4 flex w-full items-center justify-center gap-2 overflow-hidden rounded-lg border border-cyan/60 bg-cyan/10 py-3.5 font-display text-sm font-semibold tracking-[0.2em] text-cyan transition hover:bg-cyan/20 hover:shadow-glow-cyan-lg disabled:opacity-60"
              >
                <span className="relative z-10">
                  {loading ? "AUTHENTICATING…" : "SIGN IN"}
                </span>
                <svg
                  className="relative z-10 h-4 w-4 transition group-hover:translate-x-0.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M13 7l5 5m0 0l-5 5m5-5H6"
                  />
                </svg>
              </button>
            </form>

            <div className="mt-8 flex items-center gap-3 border-t border-steel/60 pt-6">
              <div className="h-1.5 w-1.5 animate-pulse-slow rounded-full bg-signal-green" />
              <span className="font-display text-[10px] tracking-[0.25em] text-mist">
                SYSTEM OPERATIONAL
              </span>
              <span className="ml-auto font-display text-[10px] tracking-[0.25em] text-mist">
                ENCRYPTED · TLS 1.3
              </span>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
