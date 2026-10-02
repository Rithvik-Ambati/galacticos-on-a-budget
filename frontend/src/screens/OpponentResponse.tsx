import type { CounterRoundResult } from "../types";

interface Props {
  opponentName: string;
  round: CounterRoundResult;
  onContinue: () => void;
}

export function OpponentResponse({ opponentName, round, onContinue }: Props) {
  const delta = round.rating_after - round.rating_before;
  return (
    <div className="screen" style={{ alignItems: "center", gap: 24 }}>
      <div>
        <span className="pill warn">COUNTER ROUND {round.round_number} OF 3</span>
        <h2 style={{ marginTop: 8 }}>{opponentName} Responds</h2>
      </div>

      <div className="row" style={{ gap: 20 }}>
        <div className="col" style={{ alignItems: "center" }}>
          <div className="text-dim2">BEFORE</div>
          <div className="headline" style={{ fontSize: 28 }}>{round.rating_before.toFixed(1)}</div>
        </div>
        <div className="text-dim2" style={{ fontSize: 22 }}>→</div>
        <div className="col" style={{ alignItems: "center" }}>
          <div className="text-dim2">AFTER</div>
          <div className="headline red" style={{ fontSize: 28 }}>{round.rating_after.toFixed(1)}</div>
        </div>
        <div className="pill" style={{ background: "rgba(240,72,90,0.12)", color: "var(--red)", borderColor: "var(--red)" }}>
          {delta >= 0 ? "+" : ""}{delta.toFixed(1)} rating
        </div>
      </div>

      <div className="card" style={{ width: 520 }}>
        <div className="headline" style={{ fontSize: 14, marginBottom: 12 }}>What They Changed</div>
        <div className="col">
          {round.moves.map((move, i) => (
            <div key={i} className="row" style={{ alignItems: "flex-start" }}>
              <div style={{ width: 4, background: "var(--gold)", borderRadius: 2, alignSelf: "stretch" }} />
              <div>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{move.move_type.replace(/_/g, " ")}</div>
                <div className="text-dim">{move.explanation}</div>
              </div>
            </div>
          ))}
          {round.moves.length === 0 && <div className="text-dim">No changes made this round.</div>}
        </div>
      </div>

      <button className="btn btn-primary" onClick={onContinue}>
        See Updated Report →
      </button>
    </div>
  );
}
