import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from plaid import ApiException
from pydantic import BaseModel
from urllib3.exceptions import HTTPError

import plaid_bank
from categorize import CATEGORIES, ai_categories, merchant_key, rule_category

DB_PATH = os.environ.get("DB_PATH", "finance.db")
DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y")
HERE = Path(__file__).parent
MAX_UPLOAD_BYTES = 1_000_000
MAX_AI_MERCHANTS = 200  # caps what one upload can cost in Claude calls on a public deploy

app = FastAPI()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, owner TEXT, date TEXT, description TEXT,"
        " amount REAL, merchant TEXT, category TEXT, source TEXT)"  # source: learned | rule | ai | default | user
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rules (owner TEXT, merchant TEXT, category TEXT, PRIMARY KEY (owner, merchant))"
    )
    return conn


def get_owner(request: Request, response: Response):
    """Each browser gets a random private id, so visitors to a public deploy never see each other's data."""
    uid = request.cookies.get("uid")
    if not uid or len(uid) > 64:
        uid = secrets.token_urlsafe(16)
        response.set_cookie(
            "uid", uid, max_age=365 * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https"
        )
    return uid


Owner = Annotated[str, Depends(get_owner)]


def parse_date(s):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"unrecognized date: {s!r}")


def parse_amount(s):
    s = s.strip().replace("$", "").replace(",", "")
    if not s:
        return 0.0
    if s.startswith("(") and s.endswith(")"):
        return -float(s[1:-1])
    return float(s)


def find_col(header, *names):
    return next((i for i, h in enumerate(header) for n in names if n in h), None)


def parse_csv(text):
    """Parse a bank CSV export into (date, description, amount) rows. Spending is negative."""
    rows = list(csv.reader(io.StringIO(text)))
    # Some banks (e.g. BofA) put summary lines above the real header, so search for it.
    for start, row in enumerate(rows):
        header = [h.strip().lower() for h in row]
        date_i = find_col(header, "date")
        desc_i = find_col(header, "description", "payee", "name", "memo")
        amt_i = find_col(header, "amount")
        debit_i, credit_i = find_col(header, "debit"), find_col(header, "credit")
        if date_i is not None and desc_i is not None and (amt_i is not None or debit_i is not None):
            break
    else:
        raise ValueError("no header row with date, description and amount columns found")

    out = []
    for row in rows[start + 1:]:
        if len(row) <= max(i for i in (date_i, desc_i, amt_i, debit_i, credit_i) if i is not None):
            continue  # blank or footer line
        if amt_i is not None:
            amount = parse_amount(row[amt_i])
        else:
            credit = parse_amount(row[credit_i]) if credit_i is not None else 0.0
            amount = credit - abs(parse_amount(row[debit_i]))
        out.append((parse_date(row[date_i]), row[desc_i].strip(), amount))
    return out


def import_rows(owner, rows):
    """rows are (date, description, amount) or, from a bank connection, (date, description, amount, bank_category)."""
    with db() as conn:
        learned = {r["merchant"]: r["category"] for r in conn.execute("SELECT * FROM rules WHERE owner = ?", (owner,))}

    # Priority: your past corrections, the bank's own category, keyword rules, Claude, then a default.
    labeled = []
    for date, desc, amount, *bank_category in rows:
        key = merchant_key(desc)
        if key in learned:
            labeled.append([owner, date, desc, amount, key, learned[key], "learned"])
        elif bank_category and bank_category[0]:
            labeled.append([owner, date, desc, amount, key, bank_category[0], "bank"])
        elif cat := rule_category(desc):
            labeled.append([owner, date, desc, amount, key, cat, "rule"])
        else:
            labeled.append([owner, date, desc, amount, key, None, None])
    ai = ai_categories(sorted({t[4] for t in labeled if t[5] is None})[:MAX_AI_MERCHANTS])
    for t in labeled:
        if t[5] is None and t[4] in ai:
            t[5], t[6] = ai[t[4]], "ai"
        elif t[5] is None:
            t[5], t[6] = ("Income" if t[3] > 0 else "Other"), "default"

    # shortcut: no dedupe, so uploading the same file twice doubles it; add a file hash check when this bites.
    with db() as conn:
        conn.executemany(
            "INSERT INTO transactions (owner, date, description, amount, merchant, category, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", labeled
        )
    return {"imported": len(rows)}


@app.post("/api/upload")
def upload(file: UploadFile, owner: Owner):
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (max 1 MB)")
    try:
        rows = parse_csv(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(400, str(e))
    return import_rows(owner, rows)


@app.post("/api/sample")
def load_sample(owner: Owner):
    return import_rows(owner, parse_csv((HERE / "sample.csv").read_text()))


@app.get("/api/transactions")
def transactions(owner: Owner):
    with db() as conn:
        return [
            dict(r) for r in conn.execute(
                "SELECT id, date, description, amount, merchant, category, source FROM transactions"
                " WHERE owner = ? ORDER BY date DESC, id DESC", (owner,)
            )
        ]


@app.get("/api/categories")
def categories():
    return CATEGORIES


class CategoryUpdate(BaseModel):
    category: str


@app.patch("/api/transactions/{tid}")
def set_category(tid: int, body: CategoryUpdate, owner: Owner):
    """Correct one transaction and remember it for every past and future charge from that merchant."""
    if body.category not in CATEGORIES:
        raise HTTPException(400, f"unknown category: {body.category}")
    with db() as conn:
        row = conn.execute("SELECT merchant FROM transactions WHERE id = ? AND owner = ?", (tid, owner)).fetchone()
        if row is None:
            raise HTTPException(404, "transaction not found")
        conn.execute("INSERT OR REPLACE INTO rules VALUES (?, ?, ?)", (owner, row["merchant"], body.category))
        conn.execute("UPDATE transactions SET category = ?, source = 'user' WHERE id = ?", (body.category, tid))
        others = conn.execute(
            "UPDATE transactions SET category = ?, source = 'learned'"
            " WHERE owner = ? AND merchant = ? AND id != ? AND source != 'user'",
            (body.category, owner, row["merchant"], tid),
        ).rowcount
    return {"updated": others + 1}


# Transfers (e.g. paying your own credit card) are money moving between your accounts, not spending.
BASE = "FROM transactions WHERE owner = ? AND category != 'Transfer'"


@app.get("/api/summary")
def summary(owner: Owner, month: str | None = None):
    """Dashboard numbers for one month (YYYY-MM), defaulting to the latest month with data."""
    with db() as conn:
        months = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT substr(date, 1, 7) m FROM transactions WHERE owner = ? ORDER BY m DESC", (owner,)
            )
        ]
        month = month or (months[0] if months else None)
        trend = conn.execute(
            "SELECT substr(date, 1, 7) month,"
            " ROUND(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 2) spent,"
            " ROUND(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 2) income"
            f" {BASE} AND substr(date, 1, 7) <= ?"
            " GROUP BY month ORDER BY month DESC LIMIT 6",
            (owner, month),
        ).fetchall()
        by_category = conn.execute(
            "SELECT category, ROUND(SUM(-amount), 2) total"
            f" {BASE} AND amount < 0 AND substr(date, 1, 7) = ?"
            " GROUP BY 1 ORDER BY total DESC",
            (owner, month),
        ).fetchall()
        top_merchants = conn.execute(
            "SELECT merchant, ROUND(SUM(-amount), 2) total, COUNT(*) count"
            f" {BASE} AND amount < 0 AND substr(date, 1, 7) = ?"
            " GROUP BY merchant ORDER BY total DESC LIMIT 5",
            (owner, month),
        ).fetchall()
    return {
        "months": months,
        "month": month,
        "trend": [dict(r) for r in reversed(trend)],  # oldest first, up to 6 months
        "by_category": [dict(r) for r in by_category],
        "top_merchants": [dict(r) for r in top_merchants],
    }


@app.get("/api/plaid/status")
def plaid_status():
    return {"enabled": plaid_bank.enabled()}


def plaid_message(e):
    try:
        return json.loads(e.body)["error_message"]
    except (TypeError, ValueError, KeyError):
        return e.reason


def require_plaid():
    if not plaid_bank.enabled():
        raise HTTPException(503, "bank connections are not configured on this server")


@app.post("/api/plaid/link_token", dependencies=[Depends(require_plaid)])
def plaid_link_token(owner: Owner):
    try:
        return {"link_token": plaid_bank.link_token(owner)}
    except ApiException as e:
        raise HTTPException(502, f"Plaid error: {plaid_message(e)}")
    except HTTPError:
        raise HTTPException(502, "could not reach Plaid")


class PublicToken(BaseModel):
    public_token: str


@app.post("/api/plaid/exchange", dependencies=[Depends(require_plaid)])
def plaid_exchange(body: PublicToken, owner: Owner):
    """Called by the browser after the user picks a bank in Plaid Link; imports that account's transactions."""
    try:
        rows = plaid_bank.fetch_transactions(body.public_token)
    except ApiException as e:
        raise HTTPException(502, f"Plaid error: {plaid_message(e)}")
    except HTTPError:
        raise HTTPException(502, "could not reach Plaid")
    return import_rows(owner, rows)


# In production the built React app is served from here, so frontend and API share one URL. Must stay last.
if (HERE.parent / "frontend" / "dist").is_dir():
    app.mount("/", StaticFiles(directory=HERE.parent / "frontend" / "dist", html=True))
