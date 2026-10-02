import type { SimulationResult } from "../types";

interface Props {
  opponentName: string;
  simulation: SimulationResult;
  onContinue: () => void;
}

export function MatchDay({ opponentName, simulation, onContinue }: Props) {
  const [us, them] = simulation.narrative_score;
  const statusLabel = simulation.went_to_penalties
    ? `PENALTIES ${simulation.penalty_score?.[0]}-${simulation.penalty_score?.[1]}`
    : simulation.went_to_extra_time
      ? "AFTER EXTRA TIME"
      : "FULL TIME";

  return (
    <div className="screen" style={{ alignItems: "center", gap: 28 }}>
      <div className="text-dim2">Match Day</div>
      <div className="row" style={{ gap: 40 }}>
        <div className="col" style={{ alignItems: "center" }}>
          <div className="card" style={{ width: 70, height: 70, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", borderColor: "var(--green)" }}>
            <span className="headline green">YOU</span>
          </div>
        </div>
        <div className="col" style={{ alignItems: "center" }}>
          <span className="pill active">{statusLabel}</span>
          <div className="headline" style={{ fontSize: 56 }}>{us} — {them}</div>
        </div>
        <div className="col" style={{ alignItems: "center" }}>
          <div className="card" style={{ width: 70, height: 70, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", borderColor: "var(--gold)" }}>
            <span className="headline gold" style={{ fontSize: 13 }}>{opponentName.slice(0, 3).toUpperCase()}</span>
          </div>
        </div>
      </div>

      <div className="card" style={{ width: 700 }}>
        <div className="headline" style={{ fontSize: 14, marginBottom: 16 }}>Match Timeline</div>
        <div className="col">
          {simulation.narrative_events.map((event, i) => (
            <div key={i} className="row text-dim">
              <span className="text-dim2" style={{ width: 40 }}>{event.minute}'</span>
              <span>{event.type === "goal" ? "⚽" : event.type === "yellow_card" ? "🟨" : "⇄"}</span>
              <span style={{ color: event.side === "user" ? "var(--green)" : "var(--gold)", fontWeight: 700 }}>
                {event.side === "user" ? "You" : opponentName}
              </span>
              <span>— {event.player_name}</span>
            </div>
          ))}
          {simulation.narrative_events.length === 0 && <div className="text-dim">A quiet one — no major incidents.</div>}
        </div>
      </div>

      <button className="btn btn-primary" onClick={onContinue}>
        View Match Report →
      </button>
    </div>
  );
}
