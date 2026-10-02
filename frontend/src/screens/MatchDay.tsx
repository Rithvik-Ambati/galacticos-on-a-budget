import { useEffect, useRef, useState } from "react";
import type { SimulationResult } from "../types";

interface Props {
  opponentName: string;
  simulation: SimulationResult;
  onContinue: () => void;
}

const REVEAL_INTERVAL_MS = 450;

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

export function MatchDay({ opponentName, simulation, onContinue }: Props) {
  const [us, them] = simulation.narrative_score;
  const statusLabel = simulation.went_to_penalties
    ? `PENALTIES ${simulation.penalty_score?.[0]}-${simulation.penalty_score?.[1]}`
    : simulation.went_to_extra_time
      ? "AFTER EXTRA TIME"
      : "FULL TIME";

  const total = simulation.narrative_events.length;
  const [visibleCount, setVisibleCount] = useState(prefersReducedMotion() ? total : 0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (prefersReducedMotion() || total === 0) {
      setVisibleCount(total);
      return;
    }
    setVisibleCount(0);
    timerRef.current = setInterval(() => {
      setVisibleCount((n) => {
        if (n + 1 >= total && timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
        return Math.min(n + 1, total);
      });
    }, REVEAL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [total]);

  function skip() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setVisibleCount(total);
  }

  const revealing = visibleCount < total;

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

      <div className="card" style={{ width: 700 }} data-testid="match-timeline">
        <div className="spread" style={{ marginBottom: 16 }}>
          <div className="headline" style={{ fontSize: 14 }}>Match Timeline</div>
          {revealing && (
            <span className="pill" style={{ cursor: "pointer" }} data-testid="skip-reveal" onClick={skip}>
              Skip ⏭
            </span>
          )}
        </div>
        <div className="col">
          {simulation.narrative_events.slice(0, visibleCount).map((event, i) => (
            <div key={i} className="row text-dim fade-in-up">
              <span className="text-dim2" style={{ width: 40 }}>{event.minute}'</span>
              <span>{event.type === "goal" ? "⚽" : event.type === "yellow_card" ? "🟨" : "⇄"}</span>
              <span style={{ color: event.side === "user" ? "var(--green)" : "var(--gold)", fontWeight: 700 }}>
                {event.side === "user" ? "You" : opponentName}
              </span>
              <span>— {event.player_name}</span>
            </div>
          ))}
          {total === 0 && <div className="text-dim">A quiet one — no major incidents.</div>}
        </div>
      </div>

      <button className="btn btn-primary" onClick={onContinue}>
        View Match Report →
      </button>
    </div>
  );
}
