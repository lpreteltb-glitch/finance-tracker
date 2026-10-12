// Bank exports shout ("TRADER JOES #552"); show all-caps names in title case, but keep
// short vowel-less acronyms and & names as-is (CVS, KFC, AT&T), and leave mixed-case names alone.
export const displayName = (s) =>
  s !== s.toUpperCase()
    ? s
    : s
        .split(" ")
        .map((w) => (w.includes("&") || /^[^AEIOU]{1,3}$/.test(w.replace(/\P{L}/gu, "")) ? w : w.toLowerCase().replace(/\p{L}/u, (c) => c.toUpperCase())))
        .join(" ");

export const money = (n, compact = false) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", ...(compact && { notation: "compact" }) });
