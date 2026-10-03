import { useState } from "react";

interface Props {
  onStart: (mode: "wc" | "ucl") => void;
  busy: boolean;
}

export function Welcome({ onStart, busy }: Props) {
  const [mode, setMode] = useState<"wc" | "ucl">("wc");

  return (
    <div className="screen" style={{ alignItems: "center", justifyContent: "center", textAlign: "center", gap: 32 }}>
      <div className="col" style={{ alignItems: "center" }}>
        <div className="green" style={{ fontWeight: 700, fontSize: 13, letterSpacing: "0.18em", textTransform: "uppercase" }}>
          Build an XI to beat a real opponent. Get coached, get countered, play it out.
        </div>
        <h1 style={{ fontSize: 72 }}>Gaffer</h1>
        <p className="text-dim" style={{ maxWidth: 520 }}>
          You're assigned a real opponent. Build an XI from anyone else on earth, within budget. The coach tells you
          where it breaks — then the opponent fights back.
        </p>
      </div>

      <div className="row" style={{ gap: 20 }}>
        <div
          className="card"
          style={{ width: 280, borderColor: mode === "wc" ? "var(--green)" : undefined, cursor: "pointer" }}
          onClick={() => setMode("wc")}
        >
          <div className="headline" style={{ fontSize: 26 }}>World Cup</div>
          <div className="text-dim2">2026 · National Teams · 1 Leg</div>
        </div>
        <div
          className="card"
          style={{ width: 280, borderColor: mode === "ucl" ? "var(--green)" : undefined, cursor: "pointer" }}
          onClick={() => setMode("ucl")}
        >
          <div className="headline" style={{ fontSize: 26 }}>Champions League</div>
          <div className="text-dim2">2025/26 · Club Sides · 2 Legs</div>
        </div>
      </div>

      <button className="btn btn-primary" disabled={busy} onClick={() => onStart(mode)}>
        {busy ? "Entering the draw..." : "Enter the Draw →"}
      </button>
      <div className="text-dim2">Max 3 players per nationality · Prices frozen per tournament</div>
    </div>
  );
}
