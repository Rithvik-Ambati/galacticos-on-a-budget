import { useState } from "react";
import * as api from "../api";
import type { LineupAnalysis, SimulationResult } from "../types";

interface Props {
  sessionId: string;
  opponentName: string;
  simulation: SimulationResult;
  matchReportText: string;
  analysis: LineupAnalysis;
  onReplay: () => void;
}

interface Message {
  role: "user" | "assistant";
  content: string;
}

const SUGGESTIONS = ["Why did we win?", "What are the odds?", "Who are the best rated players?"];

export function MatchReport({ sessionId, opponentName, simulation, matchReportText, analysis, onReplay }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [us, them] = simulation.narrative_score;

  async function send(question: string) {
    if (!question.trim() || sending) return;
    setSending(true);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }, { role: "assistant", content: "" }]);
    try {
      await api.chatStream(sessionId, question, (token) => {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { role: "assistant", content: next[next.length - 1].content + token };
          return next;
        });
      });
    } catch (e) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: "assistant", content: `Error: ${(e as Error).message}` };
        return next;
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="screen">
      <div className="spread">
        <div>
          <h2>Match Report</h2>
          <div className="text-dim2">You {us} — {them} {opponentName} · Full Time</div>
        </div>
        <button className="btn btn-ghost" onClick={onReplay}>
          New Opponent
        </button>
      </div>

      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <div className="col" style={{ width: 460 }}>
          <div className="card">
            <div className="text-dim">{matchReportText}</div>
          </div>
          <div className="card">
            <div className="headline" style={{ fontSize: 14, marginBottom: 10 }}>Key Moments</div>
            <div className="col" style={{ fontSize: 13 }}>
              {simulation.narrative_events.map((event, i) => (
                <div key={i} className="row text-dim">
                  <span className="text-dim2" style={{ width: 36 }}>{event.minute}'</span>
                  <span>{event.side === "user" ? "You" : opponentName} — {event.player_name} ({event.type})</span>
                </div>
              ))}
            </div>
          </div>
          <div className="card spread">
            <div>
              <div className="text-dim2">Manager Score</div>
              <div className="text-dim2">% of the best possible XI</div>
            </div>
            <div className="headline green" style={{ fontSize: 28 }}>
              {Math.round(analysis.manager_score.manager_score * 100)}%
            </div>
          </div>
        </div>

        <div className="card col" style={{ flex: 1, height: 560 }}>
          <div className="headline" style={{ fontSize: 14 }}>Ask the Coach</div>
          <div className="col" style={{ flex: 1, overflowY: "auto" }}>
            {messages.map((m, i) => (
              <div key={i} className={`chat-bubble ${m.role}`}>
                {m.content || "…"}
              </div>
            ))}
            {messages.length === 0 && <div className="text-dim2">Ask anything about the match or your squad.</div>}
          </div>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {SUGGESTIONS.map((s) => (
              <span key={s} className="pill" style={{ cursor: "pointer" }} onClick={() => send(s)}>
                {s}
              </span>
            ))}
          </div>
          <div className="row">
            <input
              type="text"
              placeholder="Ask about any player, stat or decision..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send(input)}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary" disabled={sending} onClick={() => send(input)}>
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
