import { useEffect, useRef, useState } from "react";
import Dashboard from "./Dashboard.jsx";
import { displayName, money } from "./format.js";

const SOURCE_LABEL = { rule: "rule", learned: "learned", bank: "bank", ai: "AI", default: "guess", user: "you" };
const SOURCE_HELP = {
  rule: "Matched a keyword rule",
  learned: "Learned from a correction you made",
  bank: "Category provided by your bank",
  ai: "Labeled by Claude",
  default: "Best guess: nothing else matched",
  user: "You set this",
};
const shortDate = (d) => new Date(`${d}T00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export default function App() {
  const [txns, setTxns] = useState(null); // null until the first load, so the welcome screen doesn't flash
  const [categories, setCategories] = useState([]);
  const [toast, setToast] = useState(null);
  const [query, setQuery] = useState("");
  const [version, setVersion] = useState(0); // bumped on every data change so the dashboard refetches
  const [plaidEnabled, setPlaidEnabled] = useState(false);
  const fileInput = useRef(null);

  const notify = (text, error = false) => setToast({ text, error, id: Date.now() });
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

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
    if (!r.ok) notify(data.detail, true);
    else notify(data.updated > 1 ? `Updated ${data.updated} ${displayName(t.merchant)} transactions to ${category}` : `Saved as ${category}`);
    load();
  }

  async function connectBank() {
    const r = await fetch("/api/plaid/link_token", { method: "POST" });
    const data = await r.json();
    if (!r.ok) return notify(data.detail, true);
    window.Plaid.create({
      token: data.link_token,
      onSuccess: async (publicToken) => {
        notify("Importing transactions from your bank…");
        const r = await fetch("/api/plaid/exchange", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ public_token: publicToken }),
        });
        const result = await r.json();
        r.ok ? notify(`Imported ${result.imported} transactions from your bank`) : notify(result.detail, true);
        load();
      },
    }).open();
  }

  async function loadSample() {
    const r = await fetch("/api/sample", { method: "POST" });
    notify(`Loaded ${(await r.json()).imported} sample transactions`);
    load();
  }

  async function upload(e) {
    const file = e.target.files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    const r = await fetch("/api/upload", { method: "POST", body });
    const data = await r.json();
    r.ok ? notify(`Imported ${data.imported} transactions from ${file.name}`) : notify(data.detail, true);
    e.target.value = "";
    load();
  }

  const q = query.trim().toLowerCase();
  const shown = (txns ?? []).filter((t) => !q || `${t.description} ${t.category}`.toLowerCase().includes(q));

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">$</span>
          Finance Tracker
        </div>
        <div className="actions">
          <input ref={fileInput} type="file" accept=".csv" hidden onChange={upload} />
          <button className="btn" onClick={() => fileInput.current.click()}>Upload CSV</button>
          {plaidEnabled && <button className="btn btn-primary" onClick={connectBank}>Connect a bank</button>}
        </div>
      </header>

      <main>
        {txns?.length === 0 && (
          <section className="card welcome">
            <h1>See where your money goes</h1>
            <p className="muted">
              Import transactions and they're sorted into categories automatically. Fix one and every charge from that
              merchant follows.
            </p>
            <div className="welcome-actions">
              <button className="btn btn-primary" onClick={loadSample}>Try it with sample data</button>
              <button className="btn" onClick={() => fileInput.current.click()}>Upload a bank CSV</button>
              {plaidEnabled && <button className="btn" onClick={connectBank}>Connect a bank</button>}
            </div>
            <ul className="features">
              <li><strong>Auto-categorized</strong>Rules, your bank's labels and AI sort every transaction.</li>
              <li><strong>Learns from you</strong>Correct a merchant once and it sticks, past and future.</li>
              <li><strong>Private</strong>Your data is tied to this browser. No sign-up, nobody else sees it.</li>
            </ul>
            {plaidEnabled && (
              <p className="hint">
                Bank connection runs in Plaid test mode: pick any bank and sign in with <code>user_good</code> /{" "}
                <code>pass_good</code>.
              </p>
            )}
          </section>
        )}

        <Dashboard version={version} />

        {txns?.length > 0 && (
          <section className="card">
            <div className="card-head">
              <h2>
                Transactions <span className="count">{shown.length}</span>
              </h2>
              <input
                className="search"
                type="search"
                placeholder="Search merchant or category"
                aria-label="Search transactions"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <table className="txns">
              <thead>
                <tr><th>Merchant</th><th>Category</th><th className="num">Amount</th></tr>
              </thead>
              <tbody>
                {shown.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <div className="merchant" title={t.description}>{displayName(t.description)}</div>
                      <div className="sub">{shortDate(t.date)}</div>
                    </td>
                    <td>
                      <div className="cat">
                        <select
                          aria-label={`Category for ${t.description}`}
                          value={t.category}
                          onChange={(e) => recategorize(t, e.target.value)}
                        >
                          {categories.map((c) => <option key={c}>{c}</option>)}
                        </select>
                        {t.source && <span className="badge" title={SOURCE_HELP[t.source]}>{SOURCE_LABEL[t.source]}</span>}
                      </div>
                    </td>
                    <td className={`num amount ${t.amount > 0 ? "pos" : ""}`}>
                      {t.amount > 0 ? "+" : ""}{money(t.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shown.length === 0 && <p className="muted empty">No transactions match “{query}”.</p>}
          </section>
        )}
      </main>

      <div className="toast-region" role="status" aria-live="polite">
        {toast && <div key={toast.id} className={`toast ${toast.error ? "toast-error" : ""}`}>{toast.text}</div>}
      </div>
    </>
  );
}
