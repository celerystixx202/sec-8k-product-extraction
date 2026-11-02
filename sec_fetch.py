"""
sec_fetch.py - Download SEC Form 8-K filings for a list of tickers.

Pipeline:
  1. ticker -> CIK      using https://www.sec.gov/files/company_tickers.json
  2. CIK    -> 8-K list using the EDGAR browse-edgar Atom feed
  3. 8-K    -> text     by downloading the primary document and stripping HTML

The SEC requires a descriptive User-Agent header and asks clients to stay
under 10 requests per second, so every request goes through sec_get(),
which sets the header and sleeps briefly.
"""

import json
import os
import re
import time
from datetime import datetime

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_AGENT = os.environ.get("SEC_USER_AGENT", "Brendan Fuller brendanfuller1@gmail.com")
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}
REQUEST_DELAY = 0.15  # seconds between requests (~6-7 req/s, under SEC's 10/s cap)

TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={cik}&type=8-K&count={count}&output=atom"
)

CACHE_DIR = "cache"  # downloaded filings are cached here so reruns are fast


def sec_get(url: str, retries: int = 4) -> requests.Response:
    """
    GET a URL from the SEC with the required headers and a polite delay.
    EDGAR occasionally returns 503 under load, so retry with backoff.
    """
    for attempt in range(retries):
        time.sleep(REQUEST_DELAY)
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code in (429, 503) and attempt < retries - 1:
            time.sleep(2 ** attempt * 2)  # 2s, 4s, 8s
            continue
        resp.raise_for_status()
        return resp


# ---------------------------------------------------------------------------
# Step 1: ticker -> CIK
# ---------------------------------------------------------------------------
def load_ticker_map() -> dict:
    """Return {ticker: {"cik": "0000320193", "name": "Apple Inc."}} for all SEC-registered tickers."""
    data = sec_get(TICKER_URL).json()
    out = {}
    for row in data.values():
        out[row["ticker"].upper()] = {
            "cik": str(row["cik_str"]).zfill(10),  # CIKs are zero-padded to 10 digits
            "name": row["title"],
        }
    return out


# ---------------------------------------------------------------------------
# Step 2: CIK -> list of 8-K filings
# ---------------------------------------------------------------------------
def list_8k_filings(cik: str, count: int = 40) -> list:
    """
    Parse the EDGAR Atom feed for one company and return a list of dicts:
      {"accession": ..., "filed": "YYYY-MM-DD", "index_url": ..., "title": ...}
    """
    xml = sec_get(FEED_URL.format(cik=cik, count=count)).text
    soup = BeautifulSoup(xml, "xml")
    filings = []
    for entry in soup.find_all("entry"):
        title = entry.title.text if entry.title else ""
        # Only plain 8-K (skip 8-K/A amendments, which usually just fix exhibits)
        if not title.startswith("8-K "):
            continue
        link = entry.find("link")["href"]
        filed = entry.find("filing-date").text if entry.find("filing-date") else ""
        acc = entry.find("accession-number").text if entry.find("accession-number") else ""
        filings.append(
            {"accession": acc, "filed": filed, "index_url": link, "title": title}
        )
    return filings


# ---------------------------------------------------------------------------
# Step 3: filing index -> primary document text
# ---------------------------------------------------------------------------
def get_doc_urls(index_url: str) -> list:
    """
    An 8-K filing has an index page listing its documents. Return the URLs of
    the primary document (Type '8-K') and any press-release exhibits
    (Type 'EX-99.1', 'EX-99.2', ...). Product announcements almost always live
    in the EX-99 press release, so we need both.
    """
    html = sec_get(index_url).text
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="tableFile")
    if not table:
        return []
    urls = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        doc_type = cells[3].text.strip()
        a = cells[2].find("a")
        if not a:
            continue
        href = a["href"].replace("/ix?doc=", "")  # strip inline-XBRL viewer prefix
        if not href.lower().endswith((".htm", ".html", ".txt")):
            continue  # skip PDFs, images, XML
        if doc_type == "8-K" or doc_type.startswith("EX-99"):
            urls.append("https://www.sec.gov" + href)
    return urls


def html_to_text(html: str) -> str:
    """Strip tags and collapse whitespace so the LLM sees clean prose."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display:\s*none")):
        tag.decompose()
    text = soup.get_text(" ")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def fetch_filing_text(filing: dict) -> str | None:
    """Download (or load from cache) the plain text of one 8-K."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{filing['accession']}.txt")
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return f.read()

    doc_urls = get_doc_urls(filing["index_url"])
    if not doc_urls:
        return None
    parts = [html_to_text(sec_get(u).text) for u in doc_urls]
    text = "\n\n=== NEXT DOCUMENT ===\n\n".join(parts)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


# ---------------------------------------------------------------------------
# Quick manual test:  python sec_fetch.py AAPL
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    ticker = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()
    tickers = load_ticker_map()
    info = tickers[ticker]
    print(f"{ticker} -> CIK {info['cik']} ({info['name']})")

    filings = list_8k_filings(info["cik"], count=5)
    print(f"Found {len(filings)} recent 8-Ks")
    for f in filings:
        text = fetch_filing_text(f)
        print(f"  {f['filed']}  {f['accession']}  {len(text or '')} chars")
    print("\nFirst 600 chars of most recent filing:\n")
    print((fetch_filing_text(filings[0]) or "")[:600])
