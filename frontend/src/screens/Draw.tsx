interface Props {
  opponentName: string;
  onContinue: () => void;
}

export function Draw({ opponentName, onContinue }: Props) {
  return (
    <div className="screen" style={{ alignItems: "center", justifyContent: "center", textAlign: "center", gap: 28 }}>
      <div className="green" style={{ fontWeight: 700, fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase" }}>
        Opponent assigned
      </div>
      <div className="row" style={{ gap: 48 }}>
        <div className="col" style={{ alignItems: "center" }}>
          <div
            className="card"
            style={{ width: 120, height: 120, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", borderColor: "var(--green)" }}
          >
            <span className="headline green" style={{ fontSize: 28 }}>YOU</span>
          </div>
          <div className="headline">Your XI</div>
        </div>
        <div className="headline text-dim2" style={{ fontSize: 32 }}>VS</div>
        <div className="col" style={{ alignItems: "center" }}>
          <div
            className="card"
            style={{ width: 120, height: 120, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", borderColor: "var(--gold)" }}
          >
            <span className="headline gold" style={{ fontSize: 22 }}>{opponentName.slice(0, 3).toUpperCase()}</span>
          </div>
          <div className="headline">{opponentName}</div>
        </div>
      </div>
      <button className="btn btn-primary" onClick={onContinue}>
        See Scouting Report →
      </button>
    </div>
  );
}
