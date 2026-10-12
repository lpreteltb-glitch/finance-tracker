import { useEffect, useState } from "react";
import { displayName, money } from "./format.js";

const monthName = (m, opts = { month: "short", year: "numeric" }) =>
  new Date(`${m}-01T00:00`).toLocaleString("en-US", opts);

export default function Dashboard({ version }) {
  const [month, setMonth] = useState(null); // null = latest month with data
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch(`/api/summary${month ? `?month=${month}` : ""}`).then((r) => r.json()).then(setData);
  }, [month, version]);

  if (!data?.months.length) return null;

  const current = data.trend.find((t) => t.month === data.month) ?? { spent: 0, income: 0 };
  const prev = data.trend[data.trend.indexOf(current) - 1];
  const change = prev?.spent ? (current.spent - prev.spent) / prev.spent : null;
  const maxCat = Math.max(...data.by_category.map((c) => c.total), 1);
  const maxMonth = Math.max(...data.trend.map((t) => t.spent), 1);

  return (
    <section aria-label="Spending dashboard">
      <div className="section-head">
        <h1>Overview</h1>
        <select aria-label="Month" value={data.month} onChange={(e) => setMonth(e.target.value)}>
          {data.months.map((m) => <option key={m} value={m}>{monthName(m, { month: "long", year: "numeric" })}</option>)}
        </select>
      </div>

      <div className="tiles">
        <div className="card">
          <div className="tile-label">Spent</div>
          <div className="tile-value">{money(current.spent)}</div>
          {change !== null && (
            // Spending going up is bad, so up is red and down is green; the arrow and words carry it without color.
            <small className={`delta ${change > 0 ? "neg" : "pos"}`}>
              {change > 0 ? "▲" : "▼"} {Math.abs(change * 100).toFixed(0)}% vs {monthName(prev.month)}
            </small>
          )}
        </div>
        <div className="card">
          <div className="tile-label">Income</div>
          <div className="tile-value">{money(current.income)}</div>
        </div>
        <div className="card">
          <div className="tile-label">Net</div>
          <div className="tile-value">{money(current.income - current.spent)}</div>
        </div>
      </div>

      <div className="charts">
        <div className="card">
          <h2>Spending by category</h2>
          {data.by_category.map((c) => (
            <div className="hbar" key={c.category} title={`${c.category}: ${money(c.total)} (${((c.total / current.spent) * 100).toFixed(0)}% of spending)`}>
              <span>{c.category}</span>
              <span className="hbar-track">
                <span className="hbar-fill" style={{ width: `${(c.total / maxCat) * 75}%` }} />
                <span className="num">{money(c.total)}</span>
              </span>
            </div>
          ))}
        </div>

        <div className="card">
          <h2>Monthly spending</h2>
          <div className="cols">
            {data.trend.map((t) => (
              <button
                key={t.month}
                className="col"
                aria-pressed={t.month === data.month}
                aria-label={`${monthName(t.month)}: ${money(t.spent)} spent. Show this month`}
                title={`${monthName(t.month)}: ${money(t.spent)}`}
                onClick={() => setMonth(t.month)}
              >
                {money(t.spent, true)}
                <span className="col-fill" style={{ height: `${(t.spent / maxMonth) * 120}px` }} />
              </button>
            ))}
          </div>
          <div className="col-labels">
            {data.trend.map((t) => <span key={t.month}>{monthName(t.month, { month: "short" })}</span>)}
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Top merchants</h2>
        <table>
          <thead><tr><th>Merchant</th><th className="num">Visits</th><th className="num">Spent</th></tr></thead>
          <tbody>
            {data.top_merchants.map((m) => (
              <tr key={m.merchant}><td>{displayName(m.merchant)}</td><td className="num">{m.count}</td><td className="num">{money(m.total)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
