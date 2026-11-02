"""
postprocess.py - Clean the raw LLM output.

The 8B model is good at finding products but produces two kinds of noise:
  1. The same product reported again in a later filing (e.g. a quarterly
     earnings release re-listing a launch from the prior quarter).
  2. Generic non-products such as "new transmission assets" or
     "Duralast branded products" that slipped past the prompt's rules.

This script keeps the raw output in new_products_raw.csv and writes the
cleaned file to new_products.csv.

Usage:  python postprocess.py
"""

import re
import shutil

import pandas as pd

RAW = "new_products_raw.csv"
CLEAN = "new_products.csv"

# Product names matching any of these are not specific new products.
GENERIC = re.compile(
    r"^(?:new |its |the |other )"                 # "new transmission assets"
    r"|\b(?:assets|resources|infrastructure|branded products|related products|"
    r"products and services|and services|results|earnings|dividend|guidance)\b$",
    re.IGNORECASE,
)


def main():
    # First run: main.py wrote new_products.csv; preserve it as the raw file.
    try:
        pd.read_csv(RAW)
    except FileNotFoundError:
        shutil.copy(CLEAN, RAW)

    df = pd.read_csv(RAW)
    n_raw = len(df)

    # 1. Drop generic non-products
    generic_mask = df["new_product"].str.strip().str.contains(GENERIC, regex=True)
    df = df[~generic_mask]
    n_generic = int(generic_mask.sum())

    # 2. Deduplicate the same product for the same company (keep earliest filing)
    df = df.sort_values("filing_time")
    key = df["new_product"].str.lower().str.strip()
    before = len(df)
    df = df[~(df.assign(k=key).duplicated(subset=["stock_name", "k"], keep="first"))]
    n_dup = before - len(df)

    df = df.sort_values(["stock_name", "filing_time"]).reset_index(drop=True)
    df.to_csv(CLEAN, index=False, quoting=1)  # quoting=1 -> QUOTE_ALL, matches the assignment example

    print(f"raw rows:            {n_raw}")
    print(f"dropped generic:     {n_generic}")
    print(f"dropped duplicates:  {n_dup}")
    print(f"clean rows:          {len(df)}  -> {CLEAN}")
    print(f"companies with rows: {df['stock_name'].nunique()}")


if __name__ == "__main__":
    main()
