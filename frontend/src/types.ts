export interface PlayerCard {
  player_id: string;
  name: string;
  nationality: string;
  position_group: string;
  position_code: string;
  ability_score: number;
  price_eur: number;
  confidence: number;
  role_fit: Record<string, number>;
  per90: Record<string, number>;
  preferred_foot: string;
  natural_position_codes: string[];
}

export interface EligibilityResult {
  eligible: boolean;
  reason: string | null;
}

export interface PlayerSearchResult {
  player: PlayerCard;
  eligibility: EligibilityResult;
}

export interface SubRatings {
  attack: number;
  midfield_control: number;
  defence: number;
  matchup: number;
  cohesion: number;
  balance: number;
}

export interface Weakness {
  type: string;
  vertical_zone: string;
  horizontal_zone: string;
  severity: number;
  evidence: Record<string, number>;
  affected_slots: string[];
  description: string;
}

export interface Strength {
  type: string;
  vertical_zone: string;
  horizontal_zone: string;
  severity: number;
  evidence: Record<string, number>;
  affected_slots: string[];
  description: string;
}

export interface SwapSuggestion {
  weakness_type: string | null;
  out_slot: string;
  out_player_id: string;
  out_player_name: string;
  in_player: PlayerCard;
  rating_before: number;
  rating_after: number;
  rating_gain: number;
  price_delta_eur: number;
}

export interface ManagerScoreResult {
  user_rating: number;
  best_rating: number;
  manager_score: number;
}

export interface ValidationResult {
  valid: boolean;
  violations: { code: string; message: string; slot_id: string | null }[];
  budget_spent_eur: number;
  budget_left_eur: number;
  nationality_counts: Record<string, number>;
  filled_slots: number;
}

export interface LineupAnalysis {
  session_id: string;
  formation: string;
  rating: { sub_ratings: SubRatings; overall: number };
  weaknesses: Weakness[];
  strengths: Strength[];
  swaps_by_weakness: Record<string, SwapSuggestion[]>;
  manager_score: ManagerScoreResult;
  validation: ValidationResult;
  win_draw_loss: [number, number, number];
}

export interface MatchEvent {
  minute: number;
  type: string;
  side: string;
  player_name: string;
  description: string;
  player_id: string | null;
  assist_player_id: string | null;
  assist_player_name: string | null;
  zone: string | null;
}

export interface SimulationResult {
  win_pct: number;
  draw_pct: number;
  loss_pct: number;
  score_distribution: Record<string, number>;
  chance_share_by_zone: Record<string, number>;
  narrative_events: MatchEvent[];
  narrative_score: [number, number];
  went_to_extra_time: boolean;
  went_to_penalties: boolean;
  penalty_score: [number, number] | null;
}

export interface OpponentWeakZone {
  has_clear_weakness: boolean;
  horizontal_zone: string;
  zone_strength: number;
  league_average: number;
  zone_strengths: Record<string, number>;
  description: string;
}

export interface ScoutingResponse {
  opponent_team_id: string;
  attack_channels: Record<string, number>;
  press_intensity_ppda: number;
  crosses_per_match: number;
  set_piece_threat: number;
  aerial: number;
  danger_players: { player_id: string; name: string; position_code: string; ability_score: number; note: string }[];
  weak_zone: OpponentWeakZone;
  opponent_formation: string;
  opponent_lineup: Record<string, PlayerCard>;
  lineup_source: string;
}

export type Awaiting = "lineup" | "decision" | "question" | null;

export interface CounterMove {
  move_type: string;
  slot_id: string;
  player_out_name: string | null;
  player_in_name: string | null;
  targeted_zone: string | null;
  explanation: string;
}

export interface CounterRoundResult {
  round_number: number;
  moves: CounterMove[];
  rating_before: number;
  rating_after: number;
  opponent_formation: string;
}

export interface PlayerContribution {
  player_id: string;
  player_name: string;
  goals: number;
  assists: number;
  defensive_contribution: number;
  ability_score: number;
  score: number;
}

export interface ManOfTheMatch {
  player_id: string;
  player_name: string;
  contributions: PlayerContribution[];
}

export interface PostMatchItem {
  type: string;
  category: "weakness" | "strength";
  horizontal_zone: string;
  outcome: "exposed" | "held" | "paid_off" | "unexpectedly_breached" | "inconclusive";
  evidence: Record<string, number>;
  description: string;
}

export interface PostMatchAnalysis {
  items: PostMatchItem[];
}

export interface DecisionResponse {
  awaiting: Awaiting;
  counter_round: number | null;
  last_counter_round: CounterRoundResult | null;
  analysis: LineupAnalysis | null;
  coach_report_text: string | null;
  simulation: SimulationResult | null;
  match_report_text: string | null;
  man_of_the_match: ManOfTheMatch | null;
  post_match_analysis: PostMatchAnalysis | null;
}

export interface SessionStateResponse {
  session_id: string;
  mode: string;
  opponent_team_id: string | null;
  formation: string | null;
  lineup_assignments: Record<string, string>;
  counter_round: number;
  awaiting: Awaiting;
  analysis: LineupAnalysis | null;
  simulation: SimulationResult | null;
  man_of_the_match: ManOfTheMatch | null;
  messages: { role: string; content: string }[];
}
