import { useState } from "react";
import * as api from "./api";
import { BuildXI } from "./screens/BuildXI";
import { CoachReport } from "./screens/CoachReport";
import { Draw } from "./screens/Draw";
import { MatchDay } from "./screens/MatchDay";
import { MatchReport } from "./screens/MatchReport";
import { OpponentResponse } from "./screens/OpponentResponse";
import { Scouting } from "./screens/Scouting";
import { Welcome } from "./screens/Welcome";
import type { CounterRoundResult, LineupAnalysis, PlayerCard, ScoutingResponse, SimulationResult } from "./types";

type Screen = "welcome" | "draw" | "scouting" | "build" | "coach" | "opponent_response" | "match_day" | "match_report";

export default function App() {
  const [screen, setScreen] = useState<Screen>("welcome");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [opponentName, setOpponentName] = useState("");
  const [scouting, setScouting] = useState<ScoutingResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [playersById, setPlayersById] = useState<Record<string, PlayerCard>>({});
  const [analysis, setAnalysis] = useState<LineupAnalysis | null>(null);
  const [coachReportText, setCoachReportText] = useState("");
  const [lastCounterRound, setLastCounterRound] = useState<CounterRoundResult | null>(null);
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [matchReportText, setMatchReportText] = useState("");
  const [counterRound, setCounterRound] = useState(0);

  async function startGame(mode: "wc" | "ucl") {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createSession(mode);
      setSessionId(created.session_id);
      const drawn = await api.draw(created.session_id);
      setOpponentName(drawn.opponent_name);
      setScreen("draw");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function goToScouting() {
    if (!sessionId) return;
    const result = await api.scout(sessionId);
    setScouting(result);
    setScreen("scouting");
  }

  async function handleAnalyse(formation: string, newAssignments: Record<string, string>, players: Record<string, PlayerCard>) {
    if (!sessionId) return;
    setError(null);
    setAssignments(newAssignments);
    setPlayersById((prev) => ({ ...prev, ...players }));
    try {
      const result = await api.analyseLineup(sessionId, formation, newAssignments);
      setAnalysis(result.analysis as LineupAnalysis);
      setCoachReportText(result.coach_report_text);
      setCounterRound(0);
      setScreen("coach");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDecision(decision: "counter" | "lock_in") {
    if (!sessionId) return;
    const result = await api.decide(sessionId, decision);
    if (decision === "counter" && result.last_counter_round) {
      setLastCounterRound(result.last_counter_round);
      if (result.analysis) setAnalysis(result.analysis);
      if (result.coach_report_text) setCoachReportText(result.coach_report_text);
      setCounterRound(result.counter_round ?? counterRound + 1);
      setScreen("opponent_response");
    } else if (result.simulation) {
      setSimulation(result.simulation);
      setMatchReportText(result.match_report_text ?? "");
      setScreen("match_day");
    }
  }

  function resetToWelcome() {
    setScreen("welcome");
    setSessionId(null);
    setAssignments({});
    setAnalysis(null);
    setSimulation(null);
    setCounterRound(0);
    setError(null);
  }

  return (
    <div className="app-shell">
      {screen === "welcome" && <Welcome onStart={startGame} busy={busy} />}

      {screen === "draw" && <Draw opponentName={opponentName} onContinue={goToScouting} />}

      {screen === "scouting" && scouting && (
        <Scouting opponentName={opponentName} scouting={scouting} onContinue={() => setScreen("build")} />
      )}

      {screen === "build" && sessionId && (
        <BuildXI sessionId={sessionId} opponentName={opponentName} onAnalyse={handleAnalyse} error={error} />
      )}

      {screen === "coach" && analysis && (
        <CoachReport
          opponentName={opponentName}
          analysis={analysis}
          coachReportText={coachReportText}
          assignments={assignments}
          playersById={playersById}
          onDecision={handleDecision}
          counterRound={counterRound}
        />
      )}

      {screen === "opponent_response" && lastCounterRound && (
        <OpponentResponse opponentName={opponentName} round={lastCounterRound} onContinue={() => setScreen("coach")} />
      )}

      {screen === "match_day" && simulation && (
        <MatchDay opponentName={opponentName} simulation={simulation} onContinue={() => setScreen("match_report")} />
      )}

      {screen === "match_report" && simulation && analysis && sessionId && (
        <MatchReport
          sessionId={sessionId}
          opponentName={opponentName}
          simulation={simulation}
          matchReportText={matchReportText}
          analysis={analysis}
          onReplay={resetToWelcome}
        />
      )}
    </div>
  );
}
