"use client";

import { useCallback, useState } from "react";
import { Upload, AlertCircle, CheckCircle, Loader2 } from "lucide-react";
import { useXRayWebSocket, type JobStatus, type Prediction } from "@/hooks/useXRayWebSocket";

export default function XRayUploader() {
  const { status, result, error, analyzeImage, reset } = useXRayWebSocket();
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const handleFile = useCallback(
    (file: File) => {
      if (!file.type.startsWith("image/")) return;
      setPreview(URL.createObjectURL(file));
      analyzeImage(file);
    },
    [analyzeImage]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleReset = () => {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(null);
    reset();
  };

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-white">X-Ray Classifier</h1>
          <p className="text-gray-400 mt-1 text-sm">
            AI-assisted pneumonia detection · Powered by AWS SageMaker
          </p>
        </div>

        <label
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          className={`flex flex-col items-center justify-center w-full h-56 rounded-2xl border-2 border-dashed cursor-pointer transition-colors
            ${dragging ? "border-blue-400 bg-blue-950/30" : "border-gray-700 bg-gray-900 hover:border-gray-500"}
            ${status !== "idle" && status !== "error" ? "pointer-events-none opacity-60" : ""}`}
        >
          <input
            type="file"
            accept="image/jpeg,image/png"
            className="hidden"
            disabled={status !== "idle" && status !== "error"}
            onChange={(e) => { if (e.target.files?.[0]) handleFile(e.target.files[0]); }}
          />
          {preview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="X-ray preview" className="h-full w-full object-contain rounded-2xl p-2" />
          ) : (
            <>
              <Upload className="w-10 h-10 text-gray-500 mb-3" />
              <p className="text-gray-400 text-sm">Drop a chest X-ray here, or click to select</p>
              <p className="text-gray-600 text-xs mt-1">JPEG or PNG</p>
            </>
          )}
        </label>

        <StatusBar status={status} />

        {result && <ResultCard prediction={result.prediction} jobId={result.jobId} />}

        {error && (
          <div className="flex items-center gap-3 bg-red-950/40 border border-red-800 rounded-xl p-4 text-red-300 text-sm">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {(status === "completed" || status === "error") && (
          <button
            onClick={handleReset}
            className="w-full py-2.5 rounded-xl bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm font-medium transition-colors"
          >
            Analyze another X-ray
          </button>
        )}
      </div>
    </div>
  );
}

function StatusBar({ status }: { status: JobStatus }) {
  const steps: { key: JobStatus; label: string }[] = [
    { key: "connecting", label: "Connecting" },
    { key: "uploading", label: "Uploading" },
    { key: "processing", label: "Analyzing" },
    { key: "completed", label: "Done" },
  ];

  if (status === "idle") return null;

  const activeIndex = steps.findIndex((s) => s.key === status);

  return (
    <div className="flex items-center justify-between gap-2">
      {steps.map((step, i) => {
        const done = i < activeIndex || status === "completed";
        const active = step.key === status;
        return (
          <div key={step.key} className="flex-1 flex flex-col items-center gap-1">
            <div className={`w-full h-1.5 rounded-full transition-colors ${done || active ? "bg-blue-500" : "bg-gray-800"}`} />
            <span className={`text-xs ${active ? "text-blue-400" : done ? "text-gray-400" : "text-gray-700"}`}>
              {active && <Loader2 className="inline w-3 h-3 animate-spin mr-1" />}
              {step.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ResultCard({ prediction, jobId }: { prediction: Prediction; jobId: string }) {
  const isPneumonia = prediction.label === "PNEUMONIA";
  return (
    <div className={`rounded-2xl border p-6 space-y-4 ${isPneumonia ? "border-red-700 bg-red-950/30" : "border-green-700 bg-green-950/30"}`}>
      <div className="flex items-center gap-3">
        <CheckCircle className={`w-6 h-6 ${isPneumonia ? "text-red-400" : "text-green-400"}`} />
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wide">Diagnosis</p>
          <p className={`text-xl font-bold ${isPneumonia ? "text-red-300" : "text-green-300"}`}>
            {prediction.label}
          </p>
        </div>
        <div className="ml-auto text-right">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Confidence</p>
          <p className="text-xl font-bold text-white">{prediction.confidence}%</p>
        </div>
      </div>

      <div className="space-y-2">
        {(["NORMAL", "PNEUMONIA"] as const).map((label) => (
          <div key={label}>
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>{label}</span>
              <span>{prediction.probabilities[label]}%</span>
            </div>
            <div className="w-full bg-gray-800 rounded-full h-1.5">
              <div
                className={`h-1.5 rounded-full transition-all ${label === "PNEUMONIA" ? "bg-red-500" : "bg-green-500"}`}
                style={{ width: `${prediction.probabilities[label]}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-600">Job ID: {jobId}</p>
    </div>
  );
}
