import { useEffect, useState } from "react";
import * as api from "./api";
import { BuildXI } from "./screens/BuildXI";
import { CoachReport } from "./screens/CoachReport";
import { Draw } from "./screens/Draw";
import { MatchDay } from "./screens/MatchDay";
import { MatchReport } from "./screens/MatchReport";
import { OpponentResponse } from "./screens/OpponentResponse";
import { Scouting } from "./screens/Scouting";
import { Welcome } from "./screens/Welcome";
import type { CounterRoundResult, LineupAnalysis, ManOfTheMatch, PlayerCard, PostMatchAnalysis, ScoutingResponse, SimulationResult } from "./types";

type Screen = "welcome" | "draw" | "scouting" | "build" | "coach" | "opponent_response" | "match_day" | "match_report";

export default function App() {
  const [screen, setScreen] = useState<Screen>("welcome");
  const [isDemoData, setIsDemoData] = useState(false);
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
  const [manOfTheMatch, setManOfTheMatch] = useState<ManOfTheMatch | null>(null);
  const [postMatchAnalysis, setPostMatchAnalysis] = useState<PostMatchAnalysis | null>(null);
  const [counterRound, setCounterRound] = useState(0);
  const [rematchPrefill, setRematchPrefill] = useState<{
    formation: string;
    assignments: Record<string, string>;
    playersById: Record<string, PlayerCard>;
  } | null>(null);

  useEffect(() => {
    api.health()
      .then((res) => setIsDemoData(res.data_source === "synthetic"))
      .catch(() => setIsDemoData(false));
  }, []);

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
      setManOfTheMatch(result.man_of_the_match);
      setPostMatchAnalysis(result.post_match_analysis);
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
    setRematchPrefill(null);
    setError(null);
  }

  async function handleRematch() {
    if (!sessionId) return;
    setError(null);
    try {
      const result = await api.rematch(sessionId);
      setSessionId(result.session_id);
      setOpponentName(result.opponent_name);
      setAssignments(result.assignments);
      setPlayersById((prev) => ({ ...prev, ...result.players }));
      setRematchPrefill({ formation: result.formation, assignments: result.assignments, playersById: result.players });
      setAnalysis(null);
      setSimulation(null);
      setManOfTheMatch(null);
      setPostMatchAnalysis(null);
      setCounterRound(0);
      setScreen("build");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="app-shell">
      {isDemoData && (
        <div
          data-testid="demo-data-banner"
          style={{
            background: "var(--gold)", color: "#1a1206", fontWeight: 700, fontSize: 13,
            textAlign: "center", padding: "8px 16px", letterSpacing: "0.04em",
          }}
        >
          DEMO DATA — fictional players, not a real opponent
        </div>
      )}
      {screen === "welcome" && <Welcome onStart={startGame} busy={busy} />}

      {screen === "draw" && <Draw opponentName={opponentName} onContinue={goToScouting} />}

      {screen === "scouting" && scouting && (
        <Scouting opponentName={opponentName} scouting={scouting} onContinue={() => setScreen("build")} />
      )}

      {screen === "build" && sessionId && (
        <BuildXI
          sessionId={sessionId}
          opponentName={opponentName}
          onAnalyse={handleAnalyse}
          error={error}
          initialFormation={rematchPrefill?.formation}
          initialAssignments={rematchPrefill?.assignments}
          initialPlayersById={rematchPrefill?.playersById}
        />
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
          manOfTheMatch={manOfTheMatch}
          postMatchAnalysis={postMatchAnalysis}
          onReplay={resetToWelcome}
          onRematch={handleRematch}
        />
      )}
    </div>
  );
}
