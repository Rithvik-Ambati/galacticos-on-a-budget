import { Pitch } from "../components/Pitch";
import type { ScoutingResponse } from "../types";

interface Props {
  opponentName: string;
  scouting: ScoutingResponse;
  onContinue: () => void;
}

export function Scouting({ opponentName, scouting, onContinue }: Props) {
  return (
    <div className="screen">
      <div className="spread">
        <div>
          <h2>Scouting Report — {opponentName}</h2>
          <div className="text-dim2">Press intensity {scouting.press_intensity_ppda}/100</div>
        </div>
        <button className="btn btn-primary" onClick={onContinue}>
          Build Your XI →
        </button>
      </div>

      <div className="row" style={{ alignItems: "flex-start", gap: 20 }}>
        <div className="card" style={{ width: 340 }}>
          <div className="spread" style={{ marginBottom: 10 }}>
            <div className="headline" style={{ fontSize: 15 }}>Likely Lineup</div>
            <span className="pill" style={{ fontSize: 10 }}>{scouting.lineup_source}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }} data-testid="opponent-lineup">
            <Pitch formation={scouting.opponent_formation} assignments={scouting.opponent_lineup} />
          </div>
          {scouting.out_of_position.length > 0 && (
            <div className="col" data-testid="out-of-position" style={{ marginBottom: 16, gap: 4 }}>
              {scouting.out_of_position.map((fill) => (
                <div key={fill.slot_id} className="text-dim2" style={{ fontSize: 11 }}>
                  ⚠ {fill.player_name} ({fill.natural_group}) is playing out of position at{" "}
                  {fill.assigned_position_code} — squad too thin there
                </div>
              ))}
            </div>
          )}
          <div className="headline" style={{ fontSize: 15, marginBottom: 14 }}>Tactical Profile</div>
          <div className="col">
            {Object.entries(scouting.attack_channels).map(([channel, value]) => (
              <div key={channel}>
                <div className="spread text-dim" style={{ marginBottom: 4 }}>
                  <span>{channel} channel</span>
                  <span style={{ fontWeight: 700, color: "var(--text)" }}>{value}</span>
                </div>
                <div className="bar">
                  <div style={{ width: `${value}%` }} />
                </div>
              </div>
            ))}
            <div className="spread text-dim">
              <span>Crosses / match</span>
              <span style={{ color: "var(--text)" }}>{scouting.crosses_per_match}</span>
            </div>
            <div className="spread text-dim">
              <span>Set-piece threat</span>
              <span style={{ color: "var(--text)" }}>{scouting.set_piece_threat}</span>
            </div>
            <div className="spread text-dim">
              <span>Aerial threat</span>
              <span style={{ color: "var(--text)" }}>{scouting.aerial}</span>
            </div>
          </div>
        </div>

        <div className="col" style={{ flex: 1, gap: 20 }}>
          <div className="card">
            <div className="headline" style={{ fontSize: 15, marginBottom: 14 }}>Danger Players</div>
            <div className="col">
              {scouting.danger_players.map((dp) => (
                <div key={dp.player_id} className="spread" style={{ background: "var(--surface-2)", borderRadius: 10, padding: "10px 14px" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{dp.name}</div>
                    <div className="text-dim2">{dp.position_code}</div>
                  </div>
                  <div className="gold headline" style={{ fontSize: 20 }}>{Math.round(dp.ability_score)}</div>
                  <div className="text-dim" style={{ maxWidth: 280 }}>{dp.note}</div>
                </div>
              ))}
            </div>
          </div>

          <div
            className="card"
            data-testid="opponent-weak-zone"
            style={{ borderColor: scouting.weak_zone.has_clear_weakness ? "var(--red)" : undefined }}
          >
            <div className="headline" style={{ fontSize: 15, marginBottom: 10 }}>Where They're Weak</div>
            <div className={scouting.weak_zone.has_clear_weakness ? "red" : "text-dim"}>
              {scouting.weak_zone.description}
            </div>
            <div className="row" style={{ gap: 16, marginTop: 10 }}>
              {Object.entries(scouting.weak_zone.zone_strengths).map(([zone, value]) => (
                <div key={zone} className="text-dim2" style={{ fontSize: 12 }}>
                  {zone}: <span style={{ color: "var(--text)", fontWeight: 700 }}>{value.toFixed(0)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
