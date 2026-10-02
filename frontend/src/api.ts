import type {
  DecisionResponse,
  PlayerSearchResult,
  ScoutingResponse,
  SessionStateResponse,
  ValidationResult,
} from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = typeof body.detail === "object" ? body.detail.detail : body.detail;
    throw new Error(detail || `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function createSession(mode: "wc" | "ucl") {
  return request<{ session_id: string; mode: string }>("/sessions", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export function draw(sessionId: string) {
  return request<{ session_id: string; opponent_team_id: string; opponent_name: string; awaiting: string }>(
    `/sessions/${sessionId}/draw`,
    { method: "POST" },
  );
}

export function scout(sessionId: string) {
  return request<ScoutingResponse>(`/sessions/${sessionId}/scout`);
}

export function searchPlayers(
  sessionId: string,
  params: { q?: string; position_group?: string; slot_id?: string; maxPriceEur?: number; limit?: number },
) {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.position_group) qs.set("position_group", params.position_group);
  if (params.slot_id) qs.set("slot_id", params.slot_id);
  if (params.maxPriceEur != null) qs.set("max_price_eur", String(params.maxPriceEur));
  qs.set("limit", String(params.limit ?? 30));
  return request<{ results: PlayerSearchResult[] }>(`/sessions/${sessionId}/players/search?${qs.toString()}`);
}

export function validateLineup(sessionId: string, formation: string, assignments: Record<string, string>) {
  return request<ValidationResult>(`/sessions/${sessionId}/lineup/validate`, {
    method: "POST",
    body: JSON.stringify({ formation, assignments }),
  });
}

export function analyseLineup(sessionId: string, formation: string, assignments: Record<string, string>) {
  return request<{ analysis: SessionStateResponse["analysis"]; coach_report_text: string; awaiting: string }>(
    `/sessions/${sessionId}/lineup/analyse`,
    { method: "POST", body: JSON.stringify({ formation, assignments }) },
  );
}

export function decide(sessionId: string, decision: "counter" | "lock_in") {
  return request<DecisionResponse>(`/sessions/${sessionId}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export function getSessionState(sessionId: string) {
  return request<SessionStateResponse>(`/sessions/${sessionId}`);
}

export async function chatEnd(sessionId: string) {
  return request<{ ended: boolean }>(`/sessions/${sessionId}/chat/end`, { method: "POST" });
}

export async function chatStream(
  sessionId: string,
  question: string,
  onToken: (token: string) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok || !res.body) throw new Error(`chat failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const payload = line.replace(/^data:\s*/, "");
      if (!payload) continue;
      const parsed = JSON.parse(payload) as { token?: string; done?: boolean };
      if (parsed.token) onToken(parsed.token);
    }
  }
}
