"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/auth";
import { useWebSocket, WsResult } from "@/lib/websocket";
import { getTopFinding, tierBadgeClass } from "@/lib/severity";

interface Patient {
  patientId: string;
  lastLunaRiskScore: number | null;
  status: string;
}

interface Nodule {
  finding: string;
  confidence: number | string;
}

interface LatestResult {
  nodulesDetected?: Nodule[];
  clinicalSummary?: string;
}

interface PatientBarProps {
  patientId: string;
}

type UploadState = "idle" | "requesting" | "uploading" | "processing" | "done" | "error";

export default function PatientBar({ patientId }: PatientBarProps) {
  const [patient, setPatient] = useState<Patient | null>(null);
  const [latestResult, setLatestResult] = useState<LatestResult | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [result, setResult] = useState<WsResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeJobRef = useRef<string | null>(null);
  const { connectionId, lastMessage } = useWebSocket();

  useEffect(() => {
    apiFetch<{ patient: Patient; latestResult: LatestResult | null }>(`/patients/${patientId}`)
      .then((d) => {
        setPatient(d.patient);
        setLatestResult(d.latestResult ?? null);
      })
      .catch(() => {});
  }, [patientId]);

  // Listen for WebSocket result for the active job
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === "result" && lastMessage.jobId === activeJobRef.current) {
      setResult(lastMessage);
      setUploadState("done");
    }
    if (lastMessage.type === "error" && lastMessage.jobId === activeJobRef.current) {
      setErrorMsg(lastMessage.message);
      setUploadState("error");
    }
    if (lastMessage.type === "status" && lastMessage.jobId === activeJobRef.current) {
      setUploadState("processing");
    }
  }, [lastMessage]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    setUploadState("requesting");
    setErrorMsg("");
    setResult(null);

    try {
      const ext = file.name.split(".").pop() || "dcm";
      const { uploadUrl, jobId } = await apiFetch<{ uploadUrl: string; jobId: string; s3Key: string }>(
        `/patients/${patientId}/upload`,
        {
          method: "POST",
          body: JSON.stringify({ fileExtension: ext, connectionId: connectionId ?? "" }),
        }
      );

      activeJobRef.current = jobId;
      setUploadState("uploading");

      await uploadToS3(uploadUrl, file, setUploadProgress);

      // S3 event notification auto-triggers inference; switch to processing state
      setUploadState("processing");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Upload failed");
      setUploadState("error");
    }
  };

  if (!patient) return null;

  return (
    <div className="shrink-0 border-b border-steel/40 bg-midnight/60 px-6 py-3 backdrop-blur-xl">
      <div className="mx-auto flex max-w-3xl items-center gap-4">
        {/* Patient info */}
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate/60 font-display text-[10px] font-bold text-ice">
            {patientId.slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="truncate font-mono text-xs text-ice/90" title={patientId}>{patientId}</div>
            <div className="font-display text-[9px] tracking-[0.15em] text-mist/70">PATIENT ID</div>
          </div>
          {patient.lastLunaRiskScore != null && (
            <RiskBadge
              status={patient.status}
              nodules={latestResult?.nodulesDetected ?? []}
            />
          )}
        </div>

        {/* Upload controls */}
        <div className="flex shrink-0 items-center gap-3">
          {uploadState === "idle" || uploadState === "done" || uploadState === "error" ? (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept=".dcm,.dicom,.jpg,.jpeg,.png"
                className="hidden"
                onChange={handleFileChange}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="flex items-center gap-2 rounded-md border border-cyan/40 bg-cyan/10 px-3 py-1.5 font-display text-[10px] tracking-[0.15em] text-cyan transition hover:bg-cyan/20"
              >
                <UploadIcon />
                UPLOAD DICOM
              </button>
            </>
          ) : uploadState === "requesting" ? (
            <StatusPill color="mist">PREPARING…</StatusPill>
          ) : uploadState === "uploading" ? (
            <StatusPill color="cyan">UPLOADING {uploadProgress}%</StatusPill>
          ) : uploadState === "processing" ? (
            <StatusPill color="amber">ANALYSING…</StatusPill>
          ) : null}

          {uploadState === "error" && (
            <span className="font-sans text-xs text-signal-red">{errorMsg}</span>
          )}
        </div>
      </div>

      {/* Inline result */}
      {result && uploadState === "done" && (
        <div className="mx-auto mt-3 max-w-3xl rounded-xl border border-steel/50 bg-deepnavy/60 px-4 py-3">
          <div className="flex items-start gap-4">
            {(() => {
              const top = getTopFinding(result.nodulesDetected ?? []);
              return top ? (
                <div className="text-center">
                  <div className={`font-display text-3xl font-bold tabular-nums ${top.tier === "critical" ? "text-signal-red" : top.tier === "high" ? "text-amber-400" : top.tier === "moderate" ? "text-yellow-300" : "text-emerald-400"}`}>
                    {top.score}%
                  </div>
                  <div className="font-display text-[8px] tracking-[0.2em] text-mist/60">{top.finding.toUpperCase()}</div>
                </div>
              ) : null;
            })()}
            <div className="flex-1 min-w-0">
              <p className="font-sans text-xs leading-relaxed text-ice/80">{result.clinicalSummary}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- Helpers ---------- */

function RiskBadge({ status, nodules }: { status: string; nodules: Nodule[] }) {
  const top = getTopFinding(nodules);
  if (top) {
    return (
      <span className={`shrink-0 rounded-md border px-2 py-0.5 font-display text-[9px] font-bold tracking-[0.08em] ${tierBadgeClass(top.tier)}`}>
        {top.finding.length > 14 ? top.finding.slice(0, 13) + "…" : top.finding} &middot; {top.score}%
      </span>
    );
  }
  // Fallback: status-based badge
  const color =
    status === "AI_FLAGGED_HIGH_RISK"     ? "border-signal-red/50 bg-signal-red/10 text-signal-red" :
    status === "AI_FLAGGED_MODERATE_RISK" ? "border-amber-400/50 bg-amber-400/10 text-amber-400" :
    "border-cyan/50 bg-cyan/10 text-cyan";
  return (
    <span className={`shrink-0 rounded-md border px-2 py-0.5 font-display text-[9px] font-bold tracking-[0.1em] ${color}`}>
      {status === "AI_FLAGGED_HIGH_RISK" ? "HIGH" : status === "AI_FLAGGED_MODERATE_RISK" ? "MOD" : "LOW"}
    </span>
  );
}

function StatusPill({ children, color }: { children: React.ReactNode; color: "mist" | "cyan" | "amber" }) {
  const cls =
    color === "cyan" ? "text-cyan border-cyan/40 bg-cyan/10" :
    color === "amber" ? "text-amber-400 border-amber-400/40 bg-amber-400/10" :
    "text-mist border-steel bg-slate/20";
  return (
    <span className={`rounded-md border px-3 py-1.5 font-display text-[10px] tracking-[0.15em] ${cls}`}>
      {children}
    </span>
  );
}

function UploadIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
    </svg>
  );
}

async function uploadToS3(url: string, file: File, onProgress: (pct: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(`S3 upload failed: ${xhr.status}`)));
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(file);
  });
}
