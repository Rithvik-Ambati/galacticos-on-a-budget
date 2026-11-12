// Legal-form prefixes/suffixes common in club names -- dropped before taking initials
// so e.g. "SSC Napoli" codes as "NAP" and "Club Brugge" as "BRU", not "SSC"/"CLU"
// (both of which `name.slice(0, 3)` produced -- found in friend playtesting: the
// badge showed the generic legal-form prefix instead of anything identifying).
const CLUB_AFFIXES = new Set([
  "fc", "cf", "sc", "ssc", "ac", "as", "afc", "ud", "cd", "sk", "bk", "ks", "fk", "rc", "ca", "club",
]);

export function clubShortCode(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length === 0) return "???";
  const significant = words.filter((w) => !CLUB_AFFIXES.has(w.toLowerCase()));
  const base = significant.length > 0 ? significant : words;
  if (base.length === 1) return base[0].slice(0, 3).toUpperCase();
  return base
    .slice(0, 3)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}
