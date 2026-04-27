"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSession } from "../lib/auth";

/**
 * Root page ('/').
 *
 * Static export forbids server-side redirects, so this is a client-side
 * router: read the session from localStorage and send the user to the
 * dashboard if logged in, login otherwise.
 */
export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const session = getSession();
    router.replace(session ? "/dashboard" : "/login");
  }, [router]);

  return (
    <div className="flex h-screen items-center justify-center bg-abyss font-display text-[10px] tracking-[0.3em] text-mist">
      LOADING…
    </div>
  );
}
