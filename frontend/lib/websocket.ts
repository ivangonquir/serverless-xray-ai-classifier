"use client";

import { useEffect, useRef, useState } from "react";
import { getSession } from "./auth";

export interface WsResult {
  type: "result";
  jobId: string;
  status: string;
  lunaRiskScore: number;
  riskLabel: string;
  nodulesDetected: unknown[];
  clinicalSummary: string;
  completedAt: string;
}

export interface WsStatus {
  type: "status";
  jobId: string;
  status: string;
}

export interface WsError {
  type: "error";
  jobId: string;
  message: string;
}

export type WsMessage = WsResult | WsStatus | WsError;

export function useWebSocket() {
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const url = process.env.NEXT_PUBLIC_WS_URL;
    if (!url) return;

    const session = getSession();
    const wsUrl = session?.userId ? `${url}?userId=${session.userId}` : url;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const raw = JSON.parse(event.data) as Record<string, unknown>;
        if (raw["type"] === "connected" && typeof raw["connectionId"] === "string") {
          setConnectionId(raw["connectionId"]);
        } else {
          setLastMessage(raw as unknown as WsMessage);
        }
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onerror = () => console.warn("LUNA WebSocket error");

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

  return { connectionId, lastMessage };
}
