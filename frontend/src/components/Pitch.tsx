import type { PlayerCard } from "../types";

export interface SlotDef {
  id: string;
  code: string;
  group: "GK" | "DF" | "MF" | "FW";
  x: number;
  y: number;
}

export const FORMATION_SLOTS: Record<string, SlotDef[]> = {
  "4-3-3": [
    { id: "GK", code: "GK", group: "GK", x: 50, y: 91 },
    { id: "LB", code: "LB", group: "DF", x: 15, y: 74 },
    { id: "CB1", code: "CB", group: "DF", x: 37, y: 80 },
    { id: "CB2", code: "CB", group: "DF", x: 63, y: 80 },
    { id: "RB", code: "RB", group: "DF", x: 85, y: 74 },
    { id: "DM", code: "DM", group: "MF", x: 50, y: 58 },
    { id: "LCM", code: "CM", group: "MF", x: 26, y: 46 },
    { id: "RCM", code: "CM", group: "MF", x: 74, y: 46 },
    { id: "LW", code: "LW", group: "FW", x: 18, y: 22 },
    { id: "ST", code: "ST", group: "FW", x: 50, y: 13 },
    { id: "RW", code: "RW", group: "FW", x: 82, y: 22 },
  ],
  "4-4-2": [
    { id: "GK", code: "GK", group: "GK", x: 50, y: 91 },
    { id: "LB", code: "LB", group: "DF", x: 15, y: 74 },
    { id: "CB1", code: "CB", group: "DF", x: 37, y: 80 },
    { id: "CB2", code: "CB", group: "DF", x: 63, y: 80 },
    { id: "RB", code: "RB", group: "DF", x: 85, y: 74 },
    { id: "LM", code: "LM", group: "MF", x: 18, y: 52 },
    { id: "CM1", code: "CM", group: "MF", x: 40, y: 56 },
    { id: "CM2", code: "CM", group: "MF", x: 60, y: 56 },
    { id: "RM", code: "RM", group: "MF", x: 82, y: 52 },
    { id: "ST1", code: "ST", group: "FW", x: 38, y: 16 },
    { id: "ST2", code: "ST", group: "FW", x: 62, y: 16 },
  ],
  "4-2-3-1": [
    { id: "GK", code: "GK", group: "GK", x: 50, y: 91 },
    { id: "LB", code: "LB", group: "DF", x: 15, y: 74 },
    { id: "CB1", code: "CB", group: "DF", x: 37, y: 80 },
    { id: "CB2", code: "CB", group: "DF", x: 63, y: 80 },
    { id: "RB", code: "RB", group: "DF", x: 85, y: 74 },
    { id: "DM1", code: "DM", group: "MF", x: 35, y: 58 },
    { id: "DM2", code: "DM", group: "MF", x: 65, y: 58 },
    { id: "LAM", code: "AM", group: "MF", x: 20, y: 34 },
    { id: "CAM", code: "AM", group: "MF", x: 50, y: 38 },
    { id: "RAM", code: "AM", group: "MF", x: 80, y: 34 },
    { id: "ST", code: "ST", group: "FW", x: 50, y: 14 },
  ],
  "3-5-2": [
    { id: "GK", code: "GK", group: "GK", x: 50, y: 91 },
    { id: "CB1", code: "CB", group: "DF", x: 30, y: 78 },
    { id: "CB2", code: "CB", group: "DF", x: 50, y: 82 },
    { id: "CB3", code: "CB", group: "DF", x: 70, y: 78 },
    { id: "LM", code: "LWB", group: "MF", x: 12, y: 50 },
    { id: "CM1", code: "CM", group: "MF", x: 35, y: 54 },
    { id: "CM2", code: "CM", group: "MF", x: 50, y: 58 },
    { id: "CM3", code: "CM", group: "MF", x: 65, y: 54 },
    { id: "RM", code: "RWB", group: "MF", x: 88, y: 50 },
    { id: "ST1", code: "ST", group: "FW", x: 38, y: 16 },
    { id: "ST2", code: "ST", group: "FW", x: 62, y: 16 },
  ],
  "3-4-3": [
    { id: "GK", code: "GK", group: "GK", x: 50, y: 91 },
    { id: "CB1", code: "CB", group: "DF", x: 30, y: 78 },
    { id: "CB2", code: "CB", group: "DF", x: 50, y: 82 },
    { id: "CB3", code: "CB", group: "DF", x: 70, y: 78 },
    { id: "LM", code: "LM", group: "MF", x: 15, y: 52 },
    { id: "CM1", code: "CM", group: "MF", x: 40, y: 56 },
    { id: "CM2", code: "CM", group: "MF", x: 60, y: 56 },
    { id: "RM", code: "RM", group: "MF", x: 85, y: 52 },
    { id: "LW", code: "LW", group: "FW", x: 18, y: 22 },
    { id: "ST", code: "ST", group: "FW", x: 50, y: 14 },
    { id: "RW", code: "RW", group: "FW", x: 82, y: 22 },
  ],
  "5-3-2": [
    { id: "GK", code: "GK", group: "GK", x: 50, y: 91 },
    { id: "LB", code: "LB", group: "DF", x: 10, y: 72 },
    { id: "CB1", code: "CB", group: "DF", x: 30, y: 78 },
    { id: "CB2", code: "CB", group: "DF", x: 50, y: 82 },
    { id: "CB3", code: "CB", group: "DF", x: 70, y: 78 },
    { id: "RB", code: "RB", group: "DF", x: 90, y: 72 },
    { id: "CM1", code: "CM", group: "MF", x: 30, y: 52 },
    { id: "CM2", code: "CM", group: "MF", x: 50, y: 56 },
    { id: "CM3", code: "CM", group: "MF", x: 70, y: 52 },
    { id: "ST1", code: "ST", group: "FW", x: 38, y: 16 },
    { id: "ST2", code: "ST", group: "FW", x: 62, y: 16 },
  ],
};

function zoneOf(slot: SlotDef): { vertical: string; horizontal: string } {
  const vertical = slot.y >= 70 ? "def" : slot.y >= 42 ? "mid" : "att";
  const horizontal = slot.x <= 33 ? "left" : slot.x >= 67 ? "right" : "center";
  return { vertical, horizontal };
}

interface PitchProps {
  formation: string;
  assignments: Record<string, PlayerCard | undefined>;
  onSlotClick?: (slot: SlotDef) => void;
  weakZones?: { vertical_zone: string; horizontal_zone: string }[];
  affectedSlots?: string[];
}

export function Pitch({ formation, assignments, onSlotClick, weakZones = [], affectedSlots = [] }: PitchProps) {
  const slots = FORMATION_SLOTS[formation] ?? FORMATION_SLOTS["4-3-3"];
  return (
    <div className="pitch">
      <div className="pitch-line-h" />
      <div className="pitch-circle" />
      {slots.map((slot, i) => {
        const player = assignments[slot.id];
        const { vertical, horizontal } = zoneOf(slot);
        const isWeak =
          affectedSlots.includes(slot.id) ||
          weakZones.some((w) => w.vertical_zone === vertical && w.horizontal_zone === horizontal);
        return (
          <div
            key={slot.id}
            className={`pitch-slot ${player ? "filled" : ""} ${isWeak ? "weak" : ""}`}
            style={{ left: `${slot.x}%`, top: `${slot.y}%` }}
            onClick={() => onSlotClick?.(slot)}
          >
            {player ? (
              <div className="avatar">{i + 1}</div>
            ) : (
              <div className="empty-avatar">+</div>
            )}
            <div className="label">
              {player ? (
                <>
                  {player.name} <span className="gold">{Math.round(player.ability_score)}</span>
                </>
              ) : (
                `${slot.id} — empty`
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
