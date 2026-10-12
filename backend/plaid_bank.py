"""Bank connections through Plaid's sandbox (fake banks, free). Set PLAID_CLIENT_ID and PLAID_SECRET to enable."""
import os
import time

import certifi
import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest

# Plaid's own category for each transaction -> ours. Detailed codes win over the broad primary ones.
PLAID_DETAILED = {
    "FOOD_AND_DRINK_GROCERIES": "Groceries",
    "TRANSPORTATION_GAS": "Gas",
    "RENT_AND_UTILITIES_RENT": "Rent",
}
PLAID_PRIMARY = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer",
    "TRANSFER_OUT": "Transfer",
    "LOAN_PAYMENTS": "Transfer",  # mostly credit card payments, which would double-count the card's purchases
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Shopping",
    "ENTERTAINMENT": "Entertainment",
    "MEDICAL": "Health",
    "PERSONAL_CARE": "Health",
    "TRANSPORTATION": "Transport",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Utilities",
    "BANK_FEES": "Other",
    "GENERAL_SERVICES": "Other",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
}


def enabled():
    return bool(os.environ.get("PLAID_CLIENT_ID") and os.environ.get("PLAID_SECRET"))


def client():
    config = plaid.Configuration(
        host=plaid.Environment.Sandbox,
        api_key={"clientId": os.environ["PLAID_CLIENT_ID"], "secret": os.environ["PLAID_SECRET"]},
    )
    config.ssl_ca_cert = certifi.where()  # python.org builds on macOS ship without system CA certs
    return plaid_api.PlaidApi(plaid.ApiClient(config))


def link_token(owner):
    return client().link_token_create(LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=owner),
        client_name="Finance Tracker",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    ))["link_token"]


def map_category(pfc):
    if pfc is None:
        return None
    return PLAID_DETAILED.get(pfc["detailed"]) or PLAID_PRIMARY.get(pfc["primary"])


def fetch_transactions(public_token, api=None, wait=1.0, tries=15):
    """Swap Link's one-time token for access, then pull every posted transaction as (date, description, amount, category)."""
    api = api or client()
    access_token = api.item_public_token_exchange(ItemPublicTokenExchangeRequest(public_token=public_token))["access_token"]
    # shortcut: imports once at connect and discards the access token; store it encrypted with the cursor to sync new transactions later.
    added, cursor = [], None
    for _ in range(tries):
        req = TransactionsSyncRequest(access_token=access_token, **({"cursor": cursor} if cursor else {}))
        resp = api.transactions_sync(req)
        added += resp["added"]
        cursor = resp["next_cursor"]
        if resp["has_more"]:
            continue
        # Right after connecting, Plaid may still be pulling history from the bank; poll until it's ready.
        if str(resp["transactions_update_status"]) != "NOT_READY":
            break
        time.sleep(wait)
    # Plaid's amounts are positive for money out; this app uses negative for spending.
    return [
        (t["date"].isoformat(), t.get("merchant_name") or t["name"], -t["amount"], map_category(t.get("personal_finance_category")))
        for t in added if not t["pending"]
    ]
