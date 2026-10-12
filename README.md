# Finance Tracker

Upload bank CSV exports (Chase, BofA, Capital One-style formats) and see your transactions, auto-categorized.

**Categorization**, in priority order:
1. **Your corrections:** change a category once and every past and future charge from that merchant follows.
2. **Keyword rules** (`backend/categorize.py`).
3. **Claude** labels whatever the rules miss, in one batched call per upload (optional: set `ANTHROPIC_API_KEY`).
4. **Default:** anything still unlabeled becomes *Income* (money in) or *Other* (money out), so every transaction always has a category.

Each browser gets its own private data (a random cookie id), so visitors to a public deploy never see each other's transactions.

**Dashboard:** spent / income / net for any month with change vs the previous month, spending by category, a 6-month trend (click a month to jump to it), and top merchants. Transfers between your own accounts are excluded from spending.

**Stack:** FastAPI + SQLite backend, React (Vite) frontend.

## Run

```bash
# backend (terminal 1)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8000

# frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and upload `backend/sample.csv`.

## Test

```bash
cd backend && .venv/bin/pytest
```

## Deploy (Render, free)

1. Push this folder to a GitHub repo.
2. On [render.com](https://render.com): **New → Blueprint**, pick the repo. It reads `render.yaml` and builds the `Dockerfile`.
3. Optionally paste an `ANTHROPIC_API_KEY` when asked; leave it blank to use rules only.

Free instances sleep after inactivity (first visit takes ~1 min) and the SQLite file resets on each redeploy, which is fine for a demo.
