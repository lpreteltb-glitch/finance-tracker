export const money = (n, compact = false) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", ...(compact && { notation: "compact" }) });
