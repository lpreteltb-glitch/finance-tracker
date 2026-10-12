import { useEffect, useState } from "react";
import Dashboard from "./Dashboard.jsx";
import { money } from "./format.js";
const SOURCE_LABEL = { rule: "rule", learned: "learned", bank: "bank", ai: "AI", default: "guess", user: "you" };

export default function App() {
  const [txns, setTxns] = useState([]);
  const [categories, setCategories] = useState([]);
  const [status, setStatus] = useState("");
  const [version, setVersion] = useState(0); // bumped on every data change so the dashboard refetches
  const [plaidEnabled, setPlaidEnabled] = useState(false);

  const load = () => {
    setVersion((v) => v + 1);
    return fetch("/api/transactions").then((r) => r.json()).then(setTxns);
  };
  useEffect(() => {
    load();
    fetch("/api/categories").then((r) => r.json()).then(setCategories);
    fetch("/api/plaid/status").then((r) => r.json()).then((s) => setPlaidEnabled(s.enabled));
  }, []);

  async function recategorize(t, category) {
    const r = await fetch(`/api/transactions/${t.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category }),
    });
    const data = await r.json();
    setStatus(r.ok ? `Updated ${data.updated} transaction(s) from this merchant` : `Error: ${data.detail}`);
    load();
  }

  async function connectBank() {
    const r = await fetch("/api/plaid/link_token", { method: "POST" });
    const data = await r.json();
    if (!r.ok) return setStatus(`Error: ${data.detail}`);
    window.Plaid.create({
      token: data.link_token,
      onSuccess: async (publicToken) => {
        setStatus("Importing transactions from your bank…");
        const r = await fetch("/api/plaid/exchange", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ public_token: publicToken }),
        });
        const result = await r.json();
        setStatus(r.ok ? `Imported ${result.imported} transactions from your bank` : `Error: ${result.detail}`);
        load();
      },
    }).open();
  }

  async function loadSample() {
    const r = await fetch("/api/sample", { method: "POST" });
    setStatus(`Loaded ${(await r.json()).imported} sample transactions`);
    load();
  }

  async function upload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body });
    const data = await r.json();
    setStatus(r.ok ? `Imported ${data.imported} transactions` : `Error: ${data.detail}`);
    e.target.value = "";
    load();
  }

  return (
    <main>
      <h1>Finance Tracker</h1>
      <label>
        Upload bank CSV: <input type="file" accept=".csv" onChange={upload} />
      </label>
      {plaidEnabled && (
        <p>
          Or <button onClick={connectBank}>Connect a bank</button>{" "}
          <small className="muted">
            Plaid test mode: pick any bank, sign in with <code>user_good</code> / <code>pass_good</code>
          </small>
        </p>
      )}
      {txns.length === 0 && (
        <p>
          No bank CSV handy? <button onClick={loadSample}>Load sample data</button>
        </p>
      )}
      <p role="status">{status}</p>
      <Dashboard version={version} />
      <h2>Transactions</h2>
      <table>
        <thead>
          <tr><th>Date</th><th>Description</th><th>Category</th><th className="num">Amount</th></tr>
        </thead>
        <tbody>
          {txns.map((t) => (
            <tr key={t.id}>
              <td>{t.date}</td>
              <td>{t.description}</td>
              <td>
                <select
                  aria-label={`Category for ${t.description}`}
                  value={t.category}
                  onChange={(e) => recategorize(t, e.target.value)}
                >
                  {categories.map((c) => <option key={c}>{c}</option>)}
                </select>{" "}
                {t.source && <small className="muted">{SOURCE_LABEL[t.source]}</small>}
              </td>
              <td className={`num ${t.amount < 0 ? "neg" : "pos"}`}>{money(t.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
