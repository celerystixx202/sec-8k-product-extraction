"""
main.py - End-to-end pipeline: S&P 500 tickers -> SEC 8-K filings -> LLM
extraction -> CSV of new product announcements.

Usage:
    python main.py                      # default: 100 filings, llama3.1:8b
    python main.py --max-filings 300    # process more
    python main.py --tickers AAPL NVDA  # restrict to specific tickers

Output:
    new_products.csv   one row per (filing, product)
    run_log.csv        one row per filing processed (for the report's statistics)
"""

import argparse
import csv
import os
import time
from datetime import datetime

from sec_fetch import load_ticker_map, list_8k_filings, fetch_filing_text
from extract import looks_like_product_announcement, extract_products, MODEL

OUTPUT_CSV = "new_products.csv"
LOG_CSV = "run_log.csv"
SP500_FILE = "sp500_tickers.txt"  # one ticker per line

FIELDS = ["company_name", "stock_name", "filing_time", "new_product", "product_description"]
LOG_FIELDS = ["ticker", "accession", "filing_time", "chars", "passed_filter", "llm_seconds", "n_products"]


def load_tickers(path: str) -> list:
    with open(path) as f:
        return [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]


def already_processed() -> set:
    """Accession numbers already in run_log.csv, so the script can resume after a crash."""
    if not os.path.exists(LOG_CSV):
        return set()
    with open(LOG_CSV, newline="") as f:
        return {row["accession"] for row in csv.DictReader(f)}


def append_row(path: str, fields: list, row: dict) -> None:
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        if new_file:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", help="tickers to process (default: sp500_tickers.txt)")
    ap.add_argument("--max-filings", type=int, default=100, help="stop after this many filings sent to the LLM")
    ap.add_argument("--per-company", type=int, default=10, help="most recent 8-Ks to pull per company")
    ap.add_argument("--no-filter", action="store_true", help="send every filing to the LLM (slow)")
    args = ap.parse_args()

    tickers = args.tickers or load_tickers(SP500_FILE)
    ticker_map = load_ticker_map()
    done = already_processed()
    print(f"Model: {MODEL} | tickers: {len(tickers)} | target filings: {args.max_filings} | already done: {len(done)}")

    n_llm = len(done)
    t_start = time.time()

    for ticker in tickers:
        if n_llm >= args.max_filings:
            break
        info = ticker_map.get(ticker)
        if not info:
            print(f"[{ticker}] not found in SEC ticker list, skipping")
            continue

        try:
            filings = list_8k_filings(info["cik"], count=args.per_company)
        except Exception as e:
            print(f"[{ticker}] feed error: {e}")
            continue

        for filing in filings:
            if n_llm >= args.max_filings:
                break
            if filing["accession"] in done:
                continue

            try:
                text = fetch_filing_text(filing)
            except Exception as e:
                print(f"[{ticker}] {filing['accession']} download error: {e}")
                continue
            if not text:
                continue

            passed = args.no_filter or looks_like_product_announcement(text)
            log = {
                "ticker": ticker, "accession": filing["accession"], "filing_time": filing["filed"],
                "chars": len(text), "passed_filter": passed, "llm_seconds": "", "n_products": 0,
            }

            if passed:
                t0 = time.time()
                company, products = extract_products(text)
                log["llm_seconds"] = f"{time.time() - t0:.1f}"
                log["n_products"] = len(products)
                n_llm += 1
                for p in products:
                    append_row(OUTPUT_CSV, FIELDS, {
                        "company_name": company or info["name"],
                        "stock_name": ticker,
                        "filing_time": filing["filed"],
                        "new_product": p["new_product"],
                        "product_description": p["product_description"],
                    })
                status = f"LLM {log['llm_seconds']}s -> {len(products)} product(s)"
                for p in products:
                    status += f"\n        * {p['new_product']}: {p['product_description'][:80]}"
            else:
                status = "skipped (no product keywords)"

            append_row(LOG_CSV, LOG_FIELDS, log)
            done.add(filing["accession"])
            print(f"[{ticker}] {filing['filed']} {filing['accession']}  {status}")

    elapsed = time.time() - t_start
    print(f"\nDone. {n_llm} filings sent to LLM in {elapsed/60:.1f} min. Output: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
