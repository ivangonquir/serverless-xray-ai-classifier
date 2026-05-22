"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/auth";
import { getTopFinding, tierBadgeClass, tierTextClass, type SeverityTier } from "@/lib/severity";

interface ClinicalFactors {
  smokingHistory: string;
  packYears: number;
  age: number;
  familyHistory: boolean;
}

interface Nodule {
  finding: string;
  confidence: number;
  boxes: number[][];
}

interface LatestResult {
  lunaRiskScore: number;
  riskLabel: string;
  clinicalSummary: string;
  clinicalFactors: ClinicalFactors;
  nodulesDetected: Nodule[];
  /** Presigned URL for the raw X-ray PNG (reference_outputs/.../original.png) */
  originalImageUrl?: string;
  /** Presigned URL for the annotated PNG with bounding boxes */
  annotatedImageUrl?: string;
  /** Legacy: presigned URL for the raw DICOM upload */
  imageUrl?: string;
  imagePrediction?: {
    label: string;
    reportText: string;
    malignancyScore: number;
  };
}

interface Patient {
  patientId: string;
  age: number;
  smokingHistory: string;
  packYears: number;
  familyHistory: boolean;
  comorbidities: string[];
  lastLunaRiskScore: number | null;
  status: string;
  ehrContext?: string;
}

interface PatientWorkspaceProps {
  patientId: string;
}

export default function PatientWorkspace({ patientId }: PatientWorkspaceProps) {
  const [patient, setPatient] = useState<Patient | null>(null);
  const [result, setResult] = useState<LatestResult | null>(null);

  useEffect(() => {
    apiFetch<{ patient: Patient; latestResult: LatestResult | null }>(
      `/patients/${patientId}`
    ).then((d) => {
      setPatient(d.patient);
      setResult(d.latestResult ?? null);
    }).catch(() => {});
  }, [patientId]);

  if (!patient) return null;

  return (
    <div className="flex flex-col gap-4 bg-midnight/40 px-5 py-4">
      {/* ── IMAGE VIEWER ─────────────────────────────────────────────── */}
      <div className="flex flex-col gap-2">
        <div className="font-display text-[9px] tracking-[0.2em] text-mist/60">X-RAY VIEWER</div>
        {(result?.originalImageUrl || result?.annotatedImageUrl || result?.imageUrl) ? (
          <ImageViewer
            originalUrl={result.originalImageUrl ?? result.imageUrl}
            annotatedUrl={result.annotatedImageUrl}
            nodules={result.nodulesDetected}
          />
        ) : (
          <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-steel/40 text-mist/40 font-display text-[9px] tracking-widest">
            NO IMAGE AVAILABLE
          </div>
        )}
      </div>

      {/* ── EHR + FINDINGS ───────────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        <div className="font-display text-[9px] tracking-[0.2em] text-mist/60">ELECTRONIC HEALTH RECORD</div>
        <EhrPanel patient={patient} />
        {result && <FindingsPanel result={result} />}
      </div>
    </div>
  );
}

/* ── EHR Panel ───────────────────────────────────────────────────────────
 * Shows core demographics + conditionally rich context from ehrContext.
 * Pack-years only shown for current/former smokers.
 */
function EhrPanel({ patient }: { patient: Patient }) {
  // Parse the rich EHR context stored as a JSON string from DynamoDB
  let ehr: Record<string, Record<string, unknown>> | null = null;
  try {
    if (patient.ehrContext) ehr = JSON.parse(patient.ehrContext);
  } catch { /* ignore */ }

  const demographics = (ehr?.patient_demographics ?? {}) as Record<string, string>;
  const admission = (ehr?.current_admission_context ?? {}) as Record<string, string>;
  const vitals = (ehr?.vitals_at_triage ?? {}) as Record<string, number | string>;
  const sex = demographics.sex as string | undefined;
  const chiefComplaint = admission.chief_complaint as string | undefined;
  const o2sat = vitals.oxygen_saturation_SpO2 as number | undefined;
  const isSmoker = patient.smokingHistory === "current" || patient.smokingHistory === "former";

  return (
    <div className="rounded-xl border border-steel/30 bg-deepnavy/60 px-4 py-3 space-y-2">
      <EhrRow label="PATIENT ID" value={patient.patientId.slice(0, 12) + "…"} />
      <EhrRow label="AGE" value={`${patient.age} years`} />
      {sex && <EhrRow label="SEX" value={sex} />}
      {chiefComplaint && <EhrRow label="CHIEF COMPLAINT" value={chiefComplaint} />}
      <EhrRow label="SMOKING" value={patient.smokingHistory} />
      {isSmoker && patient.packYears > 0 && (
        <EhrRow label="PACK-YEARS" value={String(patient.packYears)} />
      )}
      {patient.comorbidities?.length > 0 && (
        <EhrRow label="COMORBIDITIES" value={patient.comorbidities.join(" · ")} />
      )}
      {patient.familyHistory && (
        <EhrRow label="FAMILY HISTORY" value="Positive — oncological" />
      )}
      {o2sat != null && (
        <div className="flex items-baseline justify-between gap-2">
          <span className="shrink-0 font-display text-[9px] tracking-[0.1em] text-mist/50">O₂ SAT</span>
          <span className={`text-right font-sans text-xs break-all ${Number(o2sat) < 95 ? "text-amber-400" : "text-ice/80"}`}>
            {Number(o2sat).toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  );
}

/* ── Findings Panel ──────────────────────────────────────────────────────
 * Replaces the old "LUNA Risk Score" with a severity-ranked findings list.
 */
function FindingsPanel({ result }: { result: LatestResult }) {
  const nodules = result.nodulesDetected ?? [];
  const top = getTopFinding(nodules);

  return (
    <div className="rounded-xl border border-steel/30 bg-deepnavy/60 px-4 py-3 space-y-2">
      <div className="font-display text-[9px] tracking-[0.15em] text-mist/60">
        IMAGING ANALYSIS
      </div>

      {top ? (
        <div className="flex items-center justify-between gap-2">
          <span className="font-display text-[9px] tracking-[0.1em] text-mist/50">TOP FINDING</span>
          <span className={`rounded-md border px-2 py-0.5 font-display text-[9px] font-bold tracking-[0.08em] ${tierBadgeClass(top.tier)}`}>
            {top.finding} &middot; {top.score}%
          </span>
        </div>
      ) : (
        <EhrRow label="FINDINGS" value="None detected" />
      )}

      {nodules.length > 1 && (
        <div className="pt-1 space-y-1">
          {nodules.map((n, i) => {
            const { tier } = getSeverityTier(n.finding);
            return (
              <div key={i} className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${tierDot(tier)}`} />
                <span className={`font-sans text-[10px] ${tierTextClass(tier)}`}>{n.finding}</span>
              </div>
            );
          })}
        </div>
      )}

      {result.imagePrediction?.reportText && (
        <div className="pt-1">
          <div className="font-display text-[9px] tracking-[0.1em] text-mist/50 mb-1">
            VLM REPORT
          </div>
          <p className="font-sans text-[11px] leading-relaxed text-ice/70">
            {result.imagePrediction.reportText}
          </p>
        </div>
      )}
    </div>
  );
}

function getSeverityTier(finding: string): { tier: SeverityTier } {
  // Re-use the severity table via getTopFinding on a single item
  const top = getTopFinding([{ finding, confidence: 0 }]);
  return { tier: top?.tier ?? "low" };
}

function tierDot(tier: SeverityTier): string {
  switch (tier) {
    case "critical": return "bg-signal-red";
    case "high":     return "bg-amber-400";
    case "moderate": return "bg-yellow-300";
    case "low":      return "bg-cyan";
  }
}

/* ── Image viewer with toggle ────────────────────────────────────────────
 *
 * Shows two views:
 *   ORIGINAL   — raw X-ray PNG from reference_outputs/.../original.png
 *   ANNOTATED  — X-ray with bounding boxes from .../annotated.png
 *
 * The nodules array (from DiagnosticResultsTable) is shown as a badge
 * indicating how many findings were detected.
 *
 * TODO (Marta): For DICOM files use cornerstone.js (https://cornerstonejs.org/)
 * and render bounding boxes from the `nodules` array via a <canvas> overlay.
 * ───────────────────────────────────────────────────────────────────────── */
function ImageLightbox({
  url,
  label,
  onClose,
}: {
  url: string;
  label: string;
  onClose: () => void;
}) {
  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative max-h-[90vh] max-w-[90vw] rounded-2xl border border-steel/40 bg-deepnavy p-3 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute -right-3 -top-3 z-10 flex h-7 w-7 items-center justify-center rounded-full border border-steel/50 bg-midnight text-mist/70 hover:text-ice transition"
          aria-label="Close"
        >
          ✕
        </button>

        {/* Label */}
        <div className="mb-2 font-display text-[9px] tracking-[0.2em] text-mist/50">{label}</div>

        {/* Full-size image */}
        <img
          src={url}
          alt={label}
          className="max-h-[80vh] max-w-[85vw] rounded-xl object-contain"
        />
      </div>
    </div>
  );
}

function ImageViewer({
  originalUrl,
  annotatedUrl,
  nodules,
}: {
  originalUrl?: string;
  annotatedUrl?: string;
  nodules: Nodule[];
}) {
  const [showAnnotated, setShowAnnotated] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [lightboxLabel, setLightboxLabel] = useState("");

  const hasAnnotated = Boolean(annotatedUrl);
  const activeUrl = (showAnnotated && hasAnnotated) ? annotatedUrl! : originalUrl ?? annotatedUrl ?? "";
  const activeLabel = showAnnotated ? "VLM ANNOTATED SCAN" : "ORIGINAL X-RAY";

  return (
    <>
      <div className="flex flex-col gap-1">
        {/* Toggle buttons */}
        {hasAnnotated && (
          <div className="flex gap-1">
            <button
              onClick={() => setShowAnnotated(false)}
              className={`flex-1 rounded py-1 font-display text-[9px] tracking-widest transition ${
                !showAnnotated
                  ? "bg-cyan/20 text-cyan border border-cyan/40"
                  : "text-mist/50 hover:text-mist border border-steel/30"
              }`}
            >
              ORIGINAL
            </button>
            <button
              onClick={() => setShowAnnotated(true)}
              className={`flex-1 rounded py-1 font-display text-[9px] tracking-widest transition ${
                showAnnotated
                  ? "bg-cyan/20 text-cyan border border-cyan/40"
                  : "text-mist/50 hover:text-mist border border-steel/30"
              }`}
            >
              ANNOTATED
            </button>
          </div>
        )}

        {/* Image panel */}
        <div
          className="group relative cursor-zoom-in rounded-xl overflow-hidden border border-steel/30 bg-black"
          onClick={() => { setLightboxUrl(activeUrl); setLightboxLabel(activeLabel); }}
        >
          <img
            src={activeUrl}
            alt={showAnnotated ? "Annotated scan with findings" : "Original X-ray scan"}
            className="w-full object-contain max-h-64"
          />
          {/* Zoom hint overlay */}
          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition bg-black/30">
            <span className="rounded-lg border border-white/30 bg-black/60 px-3 py-1.5 font-display text-[9px] tracking-widest text-white/80">
              🔍 CLICK TO ZOOM
            </span>
          </div>
          {nodules.length > 0 && (
            <div className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 font-display text-[9px] tracking-widest text-amber-400">
              {nodules.length} FINDING{nodules.length > 1 ? "S" : ""} DETECTED
            </div>
          )}
          {showAnnotated && (
            <div className="absolute top-2 right-2 rounded bg-cyan/20 border border-cyan/40 px-2 py-1 font-display text-[9px] tracking-widest text-cyan">
              VLM ANNOTATED
            </div>
          )}
        </div>
      </div>

      {/* Lightbox portal */}
      {lightboxUrl && (
        <ImageLightbox
          url={lightboxUrl}
          label={lightboxLabel}
          onClose={() => setLightboxUrl(null)}
        />
      )}
    </>
  );
}

function EhrRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="shrink-0 font-display text-[9px] tracking-[0.1em] text-mist/50">
        {label}
      </span>
      <span className="text-right font-sans text-xs text-ice/80 break-all">{value}</span>
    </div>
  );
}
