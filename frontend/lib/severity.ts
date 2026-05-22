/**
 * severity.ts — Clinical finding severity table for LUNA
 *
 * Maps CheXOne/VLM finding names to a clinical severity tier and a base
 * probability score. Used by PatientBar and PatientWorkspace to drive the
 * semáforo (traffic-light) UI instead of the deprecated LUNA Risk Score.
 */

export type SeverityTier = "critical" | "high" | "moderate" | "low";

export interface FindingSeverity {
  tier: SeverityTier;
  score: number; // base probability % (0–100)
}

export interface TopFinding {
  finding: string;
  score: number;
  tier: SeverityTier;
}

// ── Severity table ────────────────────────────────────────────────────────
// Lower-cased keys for case-insensitive lookup.
const FINDING_SEVERITY: Record<string, FindingSeverity> = {
  // ── Critical — urgent clinical action required ─────────────────────────
  "malignant neoplasm":   { tier: "critical", score: 92 },
  "lung tumor":           { tier: "critical", score: 90 },
  "mass":                 { tier: "critical", score: 88 },
  "cavitation":           { tier: "critical", score: 86 },
  "pneumothorax":         { tier: "critical", score: 85 },
  "tension pneumothorax": { tier: "critical", score: 96 },

  // ── High — significant finding, expedited review ───────────────────────
  "pulmonary edema":        { tier: "high", score: 75 },
  "cardiomegaly":           { tier: "high", score: 72 },
  "aortic enlargement":     { tier: "high", score: 70 },
  "ild":                    { tier: "high", score: 68 },
  "interstitial lung disease": { tier: "high", score: 68 },
  "pleural effusion":       { tier: "high", score: 65 },
  "consolidation":          { tier: "high", score: 63 },

  // ── Moderate — monitor and follow up ──────────────────────────────────
  "nodule":           { tier: "moderate", score: 50 },
  "pleural thickening": { tier: "moderate", score: 48 },
  "hilar enlargement":  { tier: "moderate", score: 48 },
  "effusion":           { tier: "moderate", score: 46 },
  "atelectasis":        { tier: "moderate", score: 45 },
  "infiltrate":         { tier: "moderate", score: 44 },
  "opacity":            { tier: "moderate", score: 42 },

  // ── Low — incidental / low clinical significance ───────────────────────
  "other lesion":  { tier: "low", score: 28 },
  "calcification": { tier: "low", score: 22 },
  "scoliosis":     { tier: "low", score: 15 },
};

const TIER_RANK: Record<SeverityTier, number> = {
  critical: 4,
  high: 3,
  moderate: 2,
  low: 1,
};

// ── Helpers ───────────────────────────────────────────────────────────────

export function getSeverity(finding: string): FindingSeverity {
  return (
    FINDING_SEVERITY[finding.toLowerCase()] ?? { tier: "low", score: 20 }
  );
}

/**
 * Returns the most clinically important finding from a nodule list.
 * Sorts by severity tier first, then by score. The confidence field
 * (from iou_vs_gt or the seed proxy) adds a small bonus capped at 8 pts.
 */
export function getTopFinding(
  nodules: Array<{ finding: string; confidence?: number | string }>
): TopFinding | null {
  if (!nodules.length) return null;

  const scored = nodules.map((n) => {
    const sev = getSeverity(n.finding);
    const conf = typeof n.confidence === "string"
      ? parseFloat(n.confidence)
      : (n.confidence ?? 0);
    const bonus = Math.round(conf * 8);
    return {
      finding: n.finding,
      score: Math.min(sev.score + bonus, 99),
      tier: sev.tier,
      tierRank: TIER_RANK[sev.tier] ?? 0,
    };
  });

  scored.sort((a, b) => b.tierRank - a.tierRank || b.score - a.score);

  return {
    finding: scored[0].finding,
    score: scored[0].score,
    tier: scored[0].tier,
  };
}

// ── Tailwind class helpers ────────────────────────────────────────────────

/** Full badge classes (text + border + background). */
export function tierBadgeClass(tier: SeverityTier): string {
  switch (tier) {
    case "critical": return "text-signal-red  border-signal-red/50  bg-signal-red/10";
    case "high":     return "text-amber-400   border-amber-400/50   bg-amber-400/10";
    case "moderate": return "text-yellow-300  border-yellow-300/50  bg-yellow-300/10";
    case "low":      return "text-cyan        border-cyan/50        bg-cyan/10";
  }
}

/** Text-only colour class. */
export function tierTextClass(tier: SeverityTier): string {
  switch (tier) {
    case "critical": return "text-signal-red";
    case "high":     return "text-amber-400";
    case "moderate": return "text-yellow-300";
    case "low":      return "text-cyan";
  }
}

/** Dot background class for the small sidebar/bar indicator. */
export function tierDotClass(tier: SeverityTier): string {
  switch (tier) {
    case "critical": return "bg-signal-red";
    case "high":     return "bg-amber-400";
    case "moderate": return "bg-yellow-300";
    case "low":      return "bg-cyan";
  }
}
