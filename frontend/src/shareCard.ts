import type { LineupAnalysis, ManOfTheMatch, SimulationResult } from "./types";

/** B4 (screen 8 "share"): plain-text summary for "copy result", and a canvas-drawn
 * image for "download result image". Frontend-only -- no backend, no persistence;
 * everything here comes straight from props already on screen. */

export function buildShareText(
  opponentName: string,
  simulation: SimulationResult,
  analysis: LineupAnalysis,
  manOfTheMatch: ManOfTheMatch | null,
): string {
  const [us, them] = simulation.narrative_score;
  const lines = [
    "Lineup Lab — Match Result",
    `You ${us} - ${them} ${opponentName}`,
    `Rating: ${analysis.rating.overall.toFixed(1)}/100`,
  ];
  if (manOfTheMatch) {
    lines.push(`Man of the Match: ${manOfTheMatch.player_name}`);
  }
  lines.push(`Manager Score: ${Math.round(analysis.manager_score.manager_score * 100)}% of the best possible XI`);
  return lines.join("\n");
}

export function drawShareImage(
  canvas: HTMLCanvasElement,
  opponentName: string,
  simulation: SimulationResult,
  analysis: LineupAnalysis,
  manOfTheMatch: ManOfTheMatch | null,
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const [us, them] = simulation.narrative_score;
  canvas.width = 800;
  canvas.height = 450;

  ctx.fillStyle = "#0a0e13";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#253039";
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);

  ctx.fillStyle = "#3ddc84";
  ctx.font = "bold 16px Arial, sans-serif";
  ctx.fillText("LINEUP LAB · MATCH RESULT", 40, 50);

  ctx.fillStyle = "#f2f5f7";
  ctx.font = "bold 64px Arial, sans-serif";
  ctx.fillText(`${us} — ${them}`, 40, 150);

  ctx.fillStyle = "#9aa7b2";
  ctx.font = "20px Arial, sans-serif";
  ctx.fillText(`vs ${opponentName}`, 40, 185);

  ctx.fillStyle = "#f2b84b";
  ctx.font = "bold 28px Arial, sans-serif";
  ctx.fillText(`Rating ${analysis.rating.overall.toFixed(1)}/100`, 40, 250);

  ctx.fillStyle = "#f2f5f7";
  ctx.font = "18px Arial, sans-serif";
  if (manOfTheMatch) {
    ctx.fillText(`Man of the Match: ${manOfTheMatch.player_name}`, 40, 300);
  }
  ctx.fillText(
    `Manager Score: ${Math.round(analysis.manager_score.manager_score * 100)}% of the best possible XI`,
    40,
    340,
  );
}

export function downloadCanvasAsPng(canvas: HTMLCanvasElement, filename: string): void {
  const url = canvas.toDataURL("image/png");
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
