import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import { FORMATION_SLOTS, Pitch } from "../components/Pitch";
import type { PlayerCard, ValidationResult } from "../types";

const FORMATIONS = Object.keys(FORMATION_SLOTS);
const BUDGET_EUR = 1_000_000_000;

interface Props {
  sessionId: string;
  opponentName: string;
  onAnalyse: (formation: string, assignments: Record<string, string>, playersById: Record<string, PlayerCard>) => Promise<void>;
  error: string | null;
  initialFormation?: string;
  initialAssignments?: Record<string, string>;
  initialPlayersById?: Record<string, PlayerCard>;
}

export function BuildXI({
  sessionId, opponentName, onAnalyse, error,
  initialFormation, initialAssignments, initialPlayersById,
}: Props) {
  const [formation, setFormation] = useState(initialFormation ?? "4-3-3");
  const [assignments, setAssignments] = useState<Record<string, string>>(initialAssignments ?? {});
  const [playersById, setPlayersById] = useState<Record<string, PlayerCard>>(initialPlayersById ?? {});
  const [activeSlot, setActiveSlot] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [affordableOnly, setAffordableOnly] = useState(true);
  const [results, setResults] = useState<{ player: PlayerCard; eligibility: { eligible: boolean; reason: string | null } }[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const slots = FORMATION_SLOTS[formation];
  const filledCount = Object.keys(assignments).filter((s) => slots.some((sl) => sl.id === s)).length;

  const budgetLeftRaw =
    validation?.budget_left_eur ?? BUDGET_EUR - Object.values(assignments).reduce((sum, pid) => sum + (playersById[pid]?.price_eur ?? 0), 0);
  // replacing a filled slot frees that player's own price back into the budget too
  const outgoingPrice = activeSlot ? playersById[assignments[activeSlot]]?.price_eur ?? 0 : 0;
  const affordableCap = budgetLeftRaw + outgoingPrice;

  // A slot change must invalidate any in-flight search immediately -- otherwise a
  // click can land on a stale row from the *previous* slot's results before the new
  // list arrives, silently double-booking a player into two slots (rules.py's own
  // duplicate_player check catches it server-side, but the UI should never offer it).
  const requestIdRef = useRef(0);
  useEffect(() => {
    setResults([]);
  }, [activeSlot]);

  useEffect(() => {
    const activeGroup = activeSlot ? slots.find((s) => s.id === activeSlot)?.group : undefined;
    const requestId = ++requestIdRef.current;
    api
      .searchPlayers(sessionId, {
        q: query,
        position_group: activeGroup,
        slot_id: activeSlot ?? undefined,
        maxPriceEur: affordableOnly ? affordableCap : undefined,
        limit: 25,
      })
      .then((res) => {
        if (requestId !== requestIdRef.current) return; // a newer search has already started
        setResults(res.results);
        setPlayersById((prev) => {
          const next = { ...prev };
          for (const r of res.results) next[r.player.player_id] = r.player;
          return next;
        });
      })
      .catch(() => setResults([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, query, activeSlot, formation, affordableOnly, affordableCap]);

  useEffect(() => {
    if (Object.keys(assignments).length === 0) {
      setValidation(null);
      return;
    }
    api.validateLineup(sessionId, formation, assignments).then(setValidation).catch(() => setValidation(null));
  }, [sessionId, formation, assignments]);

  const pitchAssignments = useMemo(() => {
    const out: Record<string, PlayerCard | undefined> = {};
    for (const [slotId, playerId] of Object.entries(assignments)) out[slotId] = playersById[playerId];
    return out;
  }, [assignments, playersById]);

  function pickPlayer(player: PlayerCard) {
    const targetSlot = activeSlot ?? slots.find((s) => !assignments[s.id] && s.group === player.position_group)?.id;
    if (!targetSlot) return;
    setAssignments((prev) => {
      // never let the same player end up in two slots -- clear wherever else they
      // were (a stale-list click could otherwise silently double-book them).
      const next: Record<string, string> = {};
      for (const [slotId, playerId] of Object.entries(prev)) {
        if (playerId !== player.player_id) next[slotId] = playerId;
      }
      next[targetSlot] = player.player_id;
      return next;
    });
    setActiveSlot(null);
    setQuery("");
  }

  function changeFormation(next: string) {
    setFormation(next);
    setAssignments({});
    setActiveSlot(null);
  }

  const budgetLeft = budgetLeftRaw;
  const budgetSpent = BUDGET_EUR - budgetLeft;

  return (
    <div className="screen">
      <div className="topbar" style={{ margin: "-24px -32px 0", borderRadius: 0 }}>
        <div>
          <div className="headline" style={{ fontSize: 15 }}>Build XI</div>
          <div className="text-dim2">vs {opponentName}</div>
        </div>
        <div style={{ flex: 1, maxWidth: 260 }}>
          <div className="spread text-dim2" style={{ marginBottom: 4 }}>
            <span>Budget</span>
            <span className="gold" style={{ fontWeight: 700 }}>€{(budgetLeft / 1_000_000).toFixed(0)}M left</span>
          </div>
          <div className="bar">
            <div style={{ width: `${Math.min(100, (budgetSpent / BUDGET_EUR) * 100)}%`, background: "linear-gradient(90deg,#3ddc84,#f2b84b)" }} />
          </div>
        </div>
        <div className="row" style={{ flexWrap: "wrap", maxWidth: 360 }}>
          {validation &&
            Object.entries(validation.nationality_counts).map(([nat, count]) => (
              <span key={nat} className={`pill ${count >= 3 ? "warn" : ""}`}>
                {nat} {count}/3
              </span>
            ))}
        </div>
      </div>

      <div className="row" style={{ gap: 8 }}>
        <span className="text-dim2">Formation</span>
        {FORMATIONS.map((f) => (
          <span key={f} className={`pill ${f === formation ? "active" : ""}`} style={{ cursor: "pointer" }} onClick={() => changeFormation(f)}>
            {f}
          </span>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {validation && !validation.valid && (
        <div className="error-banner">
          {validation.violations.length > 0
            ? validation.violations.join("; ")
            : `${11 - validation.filled_slots} slot(s) still empty`}
        </div>
      )}

      <div className="row" style={{ alignItems: "flex-start", gap: 18 }}>
        <div className="card col" style={{ width: 320, maxHeight: 620, overflowY: "auto" }}>
          <input
            type="text"
            placeholder="Search players..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ width: "100%" }}
          />
          <div className="row">
            {activeSlot && (
              <div className="pill active">
                Filling {activeSlot}
                <span style={{ marginLeft: 8, cursor: "pointer" }} onClick={() => setActiveSlot(null)}>
                  ✕
                </span>
              </div>
            )}
            <div
              className={`pill ${affordableOnly ? "active" : ""}`}
              style={{ cursor: "pointer" }}
              onClick={() => setAffordableOnly((v) => !v)}
            >
              {affordableOnly ? "✓ " : ""}Affordable only
            </div>
          </div>
          <div className="col">
            {results.map((r) => (
              <div
                key={r.player.player_id}
                className={`player-row ${!r.eligibility.eligible ? "ineligible" : ""}`}
                onClick={() => r.eligibility.eligible && pickPlayer(r.player)}
                title={r.eligibility.reason ?? ""}
              >
                <div className="num">{r.player.position_code}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{r.player.name}</div>
                  <div className="text-dim2">{r.player.nationality} · {Math.round(r.player.ability_score)} ability</div>
                </div>
                {r.eligibility.eligible ? (
                  <div className="gold" style={{ fontWeight: 700 }}>€{(r.player.price_eur / 1_000_000).toFixed(0)}M</div>
                ) : (
                  <div className="red" style={{ fontSize: 10, textAlign: "right", maxWidth: 90 }}>{r.eligibility.reason}</div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
          <Pitch formation={formation} assignments={pitchAssignments} onSlotClick={(slot) => setActiveSlot(slot.id)} />
        </div>

        <div className="card col" style={{ width: 280 }}>
          <div className="headline" style={{ fontSize: 14 }}>Starting XI · {filledCount}/11</div>
          <div className="col" style={{ fontSize: 12 }}>
            {slots.map((slot) => {
              const player = playersById[assignments[slot.id]];
              return (
                <div key={slot.id} className="spread" style={{ padding: "7px 10px", background: player ? "var(--surface-2)" : "transparent", border: player ? "none" : "1px dashed var(--border)", borderRadius: 7 }}>
                  <span>{slot.code} · {player ? player.name : "— select —"}</span>
                  {player && <span className="gold" style={{ fontWeight: 700 }}>€{(player.price_eur / 1_000_000).toFixed(0)}M</span>}
                </div>
              );
            })}
          </div>
          <button
            className="btn btn-primary"
            disabled={!validation?.valid || filledCount < 11 || submitting}
            onClick={async () => {
              setSubmitting(true);
              try {
                await onAnalyse(formation, assignments, playersById);
              } finally {
                setSubmitting(false);
              }
            }}
          >
            {submitting ? "Analysing..." : filledCount < 11 ? `Analyse Lineup — ${11 - filledCount} left` : "Analyse Lineup"}
          </button>
        </div>
      </div>
    </div>
  );
}
