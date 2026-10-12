import pytest
from fastapi.testclient import TestClient

import categorize
import main

CHASE = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
01/15/2026,01/16/2026,STARBUCKS #123,Food & Drink,Sale,-5.75,
01/14/2026,01/15/2026,PAYROLL,,Payment,"2,500.00",
"""

BOFA = """Description,,Summary Amt.
Beginning balance as of 01/01/2026,,"1,000.00"

Date,Description,Amount,Running Bal.
2026-01-03,UBER TRIP,($12.40),987.60
"""

CAPITAL_ONE = """Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
1/5/26,1/6/26,1234,NETFLIX,Entertainment,15.49,
1/7/26,1/8/26,1234,REFUND,Other,,20.00
"""


def test_parse_chase():
    assert main.parse_csv(CHASE) == [
        ("2026-01-15", "STARBUCKS #123", -5.75),
        ("2026-01-14", "PAYROLL", 2500.0),
    ]


def test_parse_skips_preamble_and_handles_parens():
    assert main.parse_csv(BOFA) == [("2026-01-03", "UBER TRIP", -12.40)]


def test_parse_debit_credit_columns():
    assert main.parse_csv(CAPITAL_ONE) == [
        ("2026-01-05", "NETFLIX", -15.49),
        ("2026-01-07", "REFUND", 20.0),
    ]


def test_upload_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    client = TestClient(main.app)
    r = client.post("/api/upload", files={"file": ("chase.csv", CHASE)})
    assert r.json() == {"imported": 2}
    assert [t["description"] for t in client.get("/api/transactions").json()] == ["STARBUCKS #123", "PAYROLL"]


def test_upload_rejects_garbage(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    r = TestClient(main.app).post("/api/upload", files={"file": ("x.csv", "foo,bar\n1,2\n")})
    assert r.status_code == 400


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    asked = []
    monkeypatch.setattr(main, "ai_categories", lambda ms: asked.extend(ms) or {m: "Health" for m in ms if "YOGA" in m})
    c = TestClient(main.app)
    c.asked = asked
    return c


MIXED = """Date,Description,Amount
2026-02-01,UBER EATS 8812,-23.00
2026-02-02,UBER TRIP 4411,-14.00
2026-02-03,ZEN YOGA STUDIO,-9.99
2026-02-04,JOES BARBER SHOP,-30.00
2026-02-05,VENMO FROM SAM,25.00
"""


def by_desc(c):
    return {t["description"]: t for t in c.get("/api/transactions").json()}


def test_merchant_key_strips_store_numbers():
    assert categorize.merchant_key("STARBUCKS STORE 1234") == categorize.merchant_key("Starbucks Store #998")


def test_every_transaction_gets_a_category(client):
    client.post("/api/upload", files={"file": ("m.csv", MIXED)})
    t = by_desc(client)
    assert (t["UBER EATS 8812"]["category"], t["UBER EATS 8812"]["source"]) == ("Dining", "rule")
    assert t["UBER TRIP 4411"]["category"] == "Transport"
    assert (t["ZEN YOGA STUDIO"]["category"], t["ZEN YOGA STUDIO"]["source"]) == ("Health", "ai")
    assert (t["JOES BARBER SHOP"]["category"], t["JOES BARBER SHOP"]["source"]) == ("Other", "default")
    assert (t["VENMO FROM SAM"]["category"], t["VENMO FROM SAM"]["source"]) == ("Income", "default")
    assert sorted(client.asked) == ["JOES BARBER SHOP", "VENMO FROM SAM", "ZEN YOGA STUDIO"]  # only rule misses


def test_correction_applies_to_same_merchant_now_and_later(client):
    client.post("/api/upload", files={"file": ("m.csv", MIXED)})
    client.post("/api/upload", files={"file": ("m.csv", "Date,Description,Amount\n2026-03-01,UBER TRIP 9,-8.00\n")})
    tid = by_desc(client)["UBER TRIP 4411"]["id"]
    assert client.patch(f"/api/transactions/{tid}", json={"category": "Travel"}).json() == {"updated": 2}
    t = by_desc(client)
    assert (t["UBER TRIP 4411"]["category"], t["UBER TRIP 4411"]["source"]) == ("Travel", "user")
    assert (t["UBER TRIP 9"]["category"], t["UBER TRIP 9"]["source"]) == ("Travel", "learned")
    assert t["UBER EATS 8812"]["category"] == "Dining"  # different merchant untouched

    client.post("/api/upload", files={"file": ("m.csv", "Date,Description,Amount\n2026-04-01,UBER TRIP 77,-5.00\n")})
    assert by_desc(client)["UBER TRIP 77"]["category"] == "Travel"


def test_correction_validation(client):
    client.post("/api/upload", files={"file": ("m.csv", MIXED)})
    assert client.patch("/api/transactions/1", json={"category": "Bogus"}).status_code == 400
    assert client.patch("/api/transactions/999", json={"category": "Travel"}).status_code == 404


def test_ai_unavailable_does_not_break_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no saved credential profile either
    c = TestClient(main.app)
    assert c.post("/api/upload", files={"file": ("m.csv", MIXED)}).json() == {"imported": 5}
    assert all(t["category"] for t in c.get("/api/transactions").json())


SPREAD = """Date,Description,Amount
2025-12-05,STARBUCKS 1,-5.00
2025-12-20,PAYROLL,1000.00
2026-01-03,STARBUCKS 2,-6.00
2026-01-04,STARBUCKS 3,-4.00
2026-01-05,AMAZON MKTPL,-30.00
2026-01-06,JOES BARBER SHOP,-20.00
2026-01-07,CHASE CARD PAYMENT,-500.00
2026-01-15,PAYROLL,1000.00
"""


def test_summary(client):
    client.post("/api/upload", files={"file": ("s.csv", SPREAD)})
    tid = by_desc(client)["CHASE CARD PAYMENT"]["id"]
    client.patch(f"/api/transactions/{tid}", json={"category": "Transfer"})

    s = client.get("/api/summary").json()
    assert s["months"] == ["2026-01", "2025-12"] and s["month"] == "2026-01"
    assert s["trend"] == [
        {"month": "2025-12", "spent": 5.0, "income": 1000.0},
        {"month": "2026-01", "spent": 60.0, "income": 1000.0},  # card payment excluded as a transfer
    ]
    assert s["by_category"] == [
        {"category": "Shopping", "total": 30.0},
        {"category": "Other", "total": 20.0},
        {"category": "Dining", "total": 10.0},
    ]
    assert s["top_merchants"][0] == {"merchant": "AMAZON MKTPL", "total": 30.0, "count": 1}
    assert {"merchant": "STARBUCKS", "total": 10.0, "count": 2} in s["top_merchants"]

    dec = client.get("/api/summary", params={"month": "2025-12"}).json()
    assert [t["month"] for t in dec["trend"]] == ["2025-12"]  # nothing after the selected month
    assert dec["by_category"] == [{"category": "Dining", "total": 5.0}]


def test_summary_empty(client):
    assert client.get("/api/summary").json() == {
        "months": [], "month": None, "trend": [], "by_category": [], "top_merchants": []
    }


def test_visitors_cannot_see_each_others_data(client):
    client.post("/api/upload", files={"file": ("m.csv", MIXED)})
    tid = client.get("/api/transactions").json()[0]["id"]
    stranger = TestClient(main.app)  # fresh browser, no cookie
    assert stranger.get("/api/transactions").json() == []
    assert stranger.get("/api/summary").json()["months"] == []
    assert stranger.patch(f"/api/transactions/{tid}", json={"category": "Travel"}).status_code == 404


def test_upload_size_limit(client):
    big = "Date,Description,Amount\n" + "2026-01-01,X,-1.00\n" * 60_000
    assert client.post("/api/upload", files={"file": ("big.csv", big)}).status_code == 413


def test_sample_data_is_fully_categorized_by_rules(client):
    assert client.post("/api/sample").json()["imported"] > 30
    assert client.asked == []  # sample needs no AI calls
    assert {t["source"] for t in client.get("/api/transactions").json()} == {"rule"}


# --- Plaid (no network: a fake API stands in for Plaid's sandbox) ---
from datetime import date

import plaid_bank


def txn(name, amount, primary=None, detailed=None, merchant=None, pending=False):
    pfc = {"primary": primary, "detailed": detailed or ""} if primary else None
    return {"date": date(2026, 1, 5), "name": name, "merchant_name": merchant, "amount": amount,
            "pending": pending, "personal_finance_category": pfc}


class FakePlaid:
    def __init__(self, pages):
        self.pages, self.cursors = pages, []

    def item_public_token_exchange(self, req):
        assert req["public_token"] == "public-sandbox-123"
        return {"access_token": "access-sandbox-xyz"}

    def transactions_sync(self, req):
        self.cursors.append(req.get("cursor"))
        return self.pages.pop(0)


def test_fetch_transactions_pages_waits_and_converts():
    api = FakePlaid([
        {"added": [], "has_more": False, "next_cursor": "c0", "transactions_update_status": "NOT_READY"},
        {"added": [txn("SQ *WHOLE FDS", 42.5, "FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES", merchant="Whole Foods")],
         "has_more": True, "next_cursor": "c1", "transactions_update_status": "INITIAL_UPDATE_COMPLETE"},
        {"added": [txn("GUSTO PAY", -1500, "INCOME"), txn("PENDING THING", 3, "TRAVEL", pending=True),
                   txn("MYSTERY CO", 9.99)],
         "has_more": False, "next_cursor": "c2", "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"},
    ])
    rows = plaid_bank.fetch_transactions("public-sandbox-123", api=api, wait=0)
    assert rows == [
        ("2026-01-05", "Whole Foods", -42.5, "Groceries"),  # merchant name preferred, detailed category wins
        ("2026-01-05", "GUSTO PAY", 1500, "Income"),        # Plaid's negative = money in
        ("2026-01-05", "MYSTERY CO", -9.99, None),          # no Plaid category -> our own tiers decide
    ]
    assert api.cursors == [None, "c0", "c1"]


def test_plaid_disabled_returns_503(client, monkeypatch):
    monkeypatch.delenv("PLAID_CLIENT_ID", raising=False)
    assert client.get("/api/plaid/status").json() == {"enabled": False}
    assert client.post("/api/plaid/link_token").status_code == 503


def test_plaid_exchange_imports_with_bank_categories(client, monkeypatch):
    monkeypatch.setattr(plaid_bank, "enabled", lambda: True)
    monkeypatch.setattr(plaid_bank, "fetch_transactions", lambda tok: [
        ("2026-01-05", "Whole Foods", -42.5, "Groceries"),
        ("2026-01-06", "MYSTERY CO", -9.99, None),
    ])
    assert client.post("/api/plaid/exchange", json={"public_token": "p"}).json() == {"imported": 2}
    t = by_desc(client)
    assert (t["Whole Foods"]["category"], t["Whole Foods"]["source"]) == ("Groceries", "bank")
    assert (t["MYSTERY CO"]["category"], t["MYSTERY CO"]["source"]) == ("Other", "default")

    # Your own correction still beats the bank's category next time.
    client.patch(f"/api/transactions/{t['Whole Foods']['id']}", json={"category": "Shopping"})
    client.post("/api/plaid/exchange", json={"public_token": "p"})
    assert [x["category"] for x in client.get("/api/transactions").json() if x["description"] == "Whole Foods"] == ["Shopping", "Shopping"]
