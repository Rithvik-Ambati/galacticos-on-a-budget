import { useState } from "react";
import { Pitch } from "../components/Pitch";
import type { LineupAnalysis, PlayerCard } from "../types";

interface Props {
  opponentName: string;
  analysis: LineupAnalysis;
  coachReportText: string;
  assignments: Record<string, string>;
  playersById: Record<string, PlayerCard>;
  onDecision: (decision: "counter" | "lock_in") => Promise<void>;
  counterRound: number;
}

export function CoachReport({ opponentName, analysis, coachReportText, assignments, playersById, onDecision, counterRound }: Props) {
  const [busy, setBusy] = useState<"counter" | "lock_in" | null>(null);
  const [win, draw, loss] = analysis.win_draw_loss;
  const slotAssignments: Record<string, PlayerCard | undefined> = {};
  for (const [slotId, playerId] of Object.entries(assignments)) slotAssignments[slotId] = playersById[playerId];

  async function choose(decision: "counter" | "lock_in") {
    setBusy(decision);
    try {
      await onDecision(decision);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="screen">
      <div className="topbar" style={{ margin: "-24px -32px 0", borderRadius: 0 }}>
        <div>
          <h2 style={{ fontSize: 20 }}>Coach's Report</h2>
          <div className="text-dim2">vs {opponentName} · {analysis.formation} · round {counterRound}</div>
        </div>
        <div style={{ flex: 1, maxWidth: 420 }}>
          <div className="spread text-dim2" style={{ marginBottom: 4 }}>
            <span>WIN</span>
            <span>DRAW</span>
            <span>LOSS</span>
          </div>
          <div className="row" style={{ height: 10, borderRadius: 5, overflow: "hidden", gap: 0 }}>
            <div style={{ width: `${win}%`, background: "var(--green)", height: "100%" }} />
            <div style={{ width: `${draw}%`, background: "var(--text-dim2)", height: "100%" }} />
            <div style={{ width: `${loss}%`, background: "var(--red)", height: "100%" }} />
          </div>
        </div>
        <div className="card" style={{ borderColor: "var(--green)", padding: "10px 20px" }}>
          <div className="text-dim2">Overall Rating</div>
          <div className="headline green" style={{ fontSize: 32 }}>{analysis.rating.overall.toFixed(1)}</div>
        </div>
      </div>

      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <div style={{ display: "flex", justifyContent: "center" }}>
          <Pitch
            formation={analysis.formation}
            assignments={slotAssignments}
            weakZones={analysis.weaknesses.map((w) => ({ vertical_zone: w.vertical_zone, horizontal_zone: w.horizontal_zone }))}
            affectedSlots={analysis.weaknesses.flatMap((w) => w.affected_slots)}
          />
        </div>

        <div className="col" style={{ flex: 1 }}>
          <div className="card">
            <div className="text-dim" style={{ marginBottom: 8 }}>{coachReportText}</div>
          </div>

          {analysis.strengths.length > 0 && (
            <div className="card" data-testid="strengths-section">
              <div className="headline" style={{ fontSize: 14, marginBottom: 8 }}>Strengths</div>
              <div className="col" style={{ gap: 8 }}>
                {analysis.strengths.map((s, i) => (
                  <div key={i} className="spread" style={{ background: "var(--surface-2)", borderRadius: 10, padding: "8px 12px" }}>
                    <span className="green" style={{ fontWeight: 700 }}>{s.type.replace(/_/g, " ")}</span>
                    <span className="text-dim" style={{ fontSize: 13 }}>{s.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {analysis.weaknesses.slice(0, 3).map((w, i) => (
            <div key={i} className={`card ${i === 0 ? "danger" : ""}`}>
              <span className={`pill ${i === 0 ? "" : "warn"}`} style={i === 0 ? { background: "var(--red)", color: "#fff" } : {}}>
                {i === 0 ? "CRITICAL" : "MODERATE"} · {w.horizontal_zone.toUpperCase()} {w.vertical_zone.toUpperCase()}
              </span>
              <div style={{ fontWeight: 700, marginTop: 8 }}>{w.type.replace(/_/g, " ")}</div>
              <div className="text-dim" style={{ marginTop: 4 }}>{w.description}</div>
              {Object.entries(analysis.swaps_by_weakness)
                .filter(([key]) => key.startsWith(w.type))
                .slice(0, 1)
                .map(([key, swaps]) => (
                  <div key={key} className="row" style={{ marginTop: 10, gap: 10 }}>
                    {swaps.slice(0, 3).map((s) => (
                      <div key={s.in_player.player_id} className="card" style={{ flex: 1, padding: 12 }}>
                        <div className="spread text-dim2">
                          <span>OUT</span>
                          <span style={{ color: "var(--text)", fontWeight: 700 }}>{s.out_player_name}</span>
                        </div>
                        <div className="spread text-dim2" style={{ marginTop: 6 }}>
                          <span>IN</span>
                          <span className="green" style={{ fontWeight: 700 }}>{s.in_player.name}</span>
                        </div>
                        <div className="spread" style={{ marginTop: 8, fontSize: 12 }}>
                          <span className="green" style={{ fontWeight: 700 }}>Rating {s.rating_gain >= 0 ? "+" : ""}{s.rating_gain}</span>
                          <span className="gold">{s.price_delta_eur >= 0 ? "+" : ""}€{(s.price_delta_eur / 1_000_000).toFixed(0)}M</span>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
            </div>
          ))}
          {analysis.weaknesses.length === 0 && (
            <div className="card">No significant weaknesses flagged against this opponent.</div>
          )}
        </div>
      </div>

      <div className="row" style={{ justifyContent: "center", gap: 16, paddingTop: 10 }}>
        <button className="btn btn-outline" disabled={busy !== null || counterRound >= 3} onClick={() => choose("counter")}>
          {busy === "counter" ? "Countering..." : `Counter Again · ${3 - counterRound} Left`}
        </button>
        <button className="btn btn-primary" disabled={busy !== null} onClick={() => choose("lock_in")}>
          {busy === "lock_in" ? "Locking in..." : "Lock In Lineup →"}
        </button>
      </div>
    </div>
  );
}
