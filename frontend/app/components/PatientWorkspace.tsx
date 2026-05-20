"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/auth";

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
  imageUrl?: string;         // presigned S3 GET URL — valid for 1 hour
  imagePrediction?: {
    label: string;
    reportText: string;
    malignancyScore: number;
  };
}

interface Patient {
  patientId: string;
  name: string;
  age: number;
  dateOfBirth: string;
  smokingHistory: string;
  packYears: number;
  familyHistory: boolean;
  comorbidities: string[];
  lastLunaRiskScore: number | null;
  status: string;
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

    // Fetch presigned image URL from the dedicated endpoint
    apiFetch<{ imageUrl: string }>(`/patients/${patientId}/image-url`)
      .then((d) => setResult((prev) => prev ? { ...prev, imageUrl: d.imageUrl } : prev))
      .catch(() => {});
  }, [patientId]);

  if (!patient) return null;

  return (
    <div className="flex gap-4 border-b border-steel/40 bg-midnight/40 px-6 py-4">
      {/* ── LEFT PANE: Image viewer ──────────────────────────────────── */}
      <div className="flex w-1/2 flex-col gap-2">
        <div className="font-display text-[9px] tracking-[0.2em] text-mist/60">
          DICOM / IMAGE VIEWER
        </div>

        {result?.imageUrl ? (
          <ImageViewer imageUrl={result.imageUrl} nodules={result.nodulesDetected} />
        ) : (
          <div className="flex h-48 items-center justify-center rounded-xl border border-dashed border-steel/40 text-mist/40 font-display text-[9px] tracking-widest">
            NO IMAGE UPLOADED
          </div>
        )}
      </div>

      {/* ── RIGHT PANE: EHR data ─────────────────────────────────────── */}
      <div className="flex w-1/2 flex-col gap-3">
        <div className="font-display text-[9px] tracking-[0.2em] text-mist/60">
          ELECTRONIC HEALTH RECORD
        </div>

        <div className="rounded-xl border border-steel/30 bg-deepnavy/60 px-4 py-3 space-y-2">
          <EhrRow label="AGE" value={`${patient.age} years`} />
          <EhrRow label="DATE OF BIRTH" value={patient.dateOfBirth} />
          <EhrRow
            label="SMOKING HISTORY"
            value={`${patient.smokingHistory}${patient.packYears ? ` · ${patient.packYears} pack-years` : ""}`}
          />
          <EhrRow
            label="FAMILY HISTORY"
            value={patient.familyHistory ? "Positive for lung cancer" : "Negative"}
          />
          {patient.comorbidities?.length > 0 && (
            <EhrRow label="COMORBIDITIES" value={patient.comorbidities.join(", ")} />
          )}
        </div>

        {result && (
          <div className="rounded-xl border border-steel/30 bg-deepnavy/60 px-4 py-3 space-y-2">
            <div className="font-display text-[9px] tracking-[0.15em] text-mist/60">
              LATEST ANALYSIS
            </div>
            <EhrRow label="LUNA RISK SCORE" value={`${Math.round(result.lunaRiskScore)} / 100`} />
            <EhrRow label="RISK LEVEL" value={result.riskLabel} />
            {result.imagePrediction?.reportText && (
              <div>
                <div className="font-display text-[9px] tracking-[0.1em] text-mist/50 mb-1">
                  VLM REPORT
                </div>
                <p className="font-sans text-[11px] leading-relaxed text-ice/70">
                  {result.imagePrediction.reportText}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Image viewer ────────────────────────────────────────────────────────────
 *
 * TODO (Marta): Replace the <img> below with a proper DICOM viewer.
 *
 * The `imageUrl` is a presigned S3 URL valid for 1 hour. For DICOM files
 * you can use cornerstone.js (https://cornerstonejs.org/) or dwv
 * (https://github.com/ivmartel/dwv). For regular JPG/PNG the <img> works fine.
 *
 * The `nodules` array has the structure:
 *   { finding: string, confidence: number, boxes: number[][] }
 * Each box is [x1, y1, x2, y2] in pixel coordinates from the original image.
 * Draw them as overlays on the image (e.g. using a <canvas> on top of <img>).
 *
 * ───────────────────────────────────────────────────────────────────────── */
function ImageViewer({ imageUrl, nodules }: { imageUrl: string; nodules: Nodule[] }) {
  return (
    <div className="relative rounded-xl overflow-hidden border border-steel/30 bg-black">
      {/* TODO (Marta): replace with DICOM viewer + canvas overlay for bounding boxes */}
      <img
        src={imageUrl}
        alt="Patient scan"
        className="w-full object-contain max-h-64"
      />
      {nodules.length > 0 && (
        <div className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 font-display text-[9px] tracking-widest text-amber-400">
          {nodules.length} FINDING{nodules.length > 1 ? "S" : ""} DETECTED
        </div>
      )}
    </div>
  );
}

function EhrRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="shrink-0 font-display text-[9px] tracking-[0.1em] text-mist/50">
        {label}
      </span>
      <span className="text-right font-sans text-xs text-ice/80">{value}</span>
    </div>
  );
}
