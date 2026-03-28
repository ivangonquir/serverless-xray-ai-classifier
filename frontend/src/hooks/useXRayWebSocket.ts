/**
 * useXRayWebSocket
 *
 * Manages the full lifecycle of an X-ray upload + inference job:
 *   1. Connect to WebSocket
 *   2. Request a pre-signed S3 upload URL
 *   3. PUT the image directly to S3
 *   4. Listen for status/result/error messages from the backend
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type JobStatus = "idle" | "connecting" | "uploading" | "processing" | "completed" | "error";

export interface Prediction {
  label: "NORMAL" | "PNEUMONIA";
  confidence: number;
  probabilities: { NORMAL: number; PNEUMONIA: number };
}

export interface XRayResult {
  jobId: string;
  prediction: Prediction;
}

export function useXRayWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<JobStatus>("idle");
  const [result, setResult] = useState<XRayResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setError(null);
  }, []);

  const analyzeImage = useCallback((file: File) => {
    reset();

    const wsUrl = process.env.NEXT_PUBLIC_WS_URL!;
    setStatus("connecting");

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      const jobId = crypto.randomUUID();
      ws.send(
        JSON.stringify({
          action: "getUploadUrl",
          jobId,
          contentType: file.type || "image/jpeg",
        })
      );
    };

    ws.onmessage = async (event) => {
      const msg = JSON.parse(event.data);

      if (msg.type === "uploadUrl") {
        setStatus("uploading");
        try {
          const res = await fetch(msg.url, {
            method: "PUT",
            headers: { "Content-Type": file.type || "image/jpeg" },
            body: file,
          });
          if (!res.ok) throw new Error(`S3 upload failed: ${res.status}`);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : "Upload failed";
          setStatus("error");
          setError(message);
          ws.close();
        }
        return;
      }

      if (msg.type === "status" && msg.status === "processing") {
        setStatus("processing");
        return;
      }

      if (msg.type === "result") {
        setResult({ jobId: msg.jobId, prediction: msg.prediction });
        setStatus("completed");
        ws.close();
        return;
      }

      if (msg.type === "error") {
        setError(msg.message || "Inference failed");
        setStatus("error");
        ws.close();
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
      setStatus("error");
    };

    ws.onclose = () => {
      wsRef.current = null;
    };
  }, [reset]);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
    };
  }, []);

  return { status, result, error, analyzeImage, reset };
}
