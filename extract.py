"""
extract.py - Use a local LLM (via Ollama) to extract new-product announcements
from SEC 8-K filing text.

The model is asked to behave as a Named Entity Recognition (NER) tagger:
  ORGANIZATION -> company name
  PRODUCT      -> newly announced product
and to return strict JSON so Python can parse it reliably.
"""

import json
import os
import re

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
MAX_CHARS = 20_000  # ~5k tokens of filing text
NUM_CTX = 8192      # Ollama default is 2048, which would silently truncate the filing
MAX_DESC = 180      # assignment limit for product_description

# ---------------------------------------------------------------------------
# Stage 1: cheap keyword pre-filter (no LLM)
# ---------------------------------------------------------------------------
# Most 8-Ks are earnings, debt, or board changes. Only send filings to the LLM
# if they contain product-launch language. This cuts LLM calls by ~80%.
PRODUCT_KEYWORDS = re.compile(
    r"\b(launch(?:es|ed|ing)?|introduc(?:e|es|ed|ing)|launch of|unveil(?:s|ed|ing)?|"
    r"new product|product line|now available|general availability|"
    r"debut(?:s|ed)?|releas(?:es|ed|ing) (?:its|the|a) new|announc(?:es|ed) (?:the )?(?:launch|availability|release))\b",
    re.IGNORECASE,
)


def looks_like_product_announcement(text: str) -> bool:
    return bool(PRODUCT_KEYWORDS.search(text))


# ---------------------------------------------------------------------------
# Stage 2: LLM extraction
# ---------------------------------------------------------------------------
PROMPT = """You are a Named Entity Recognition (NER) system for SEC Form 8-K filings.
Identify entities of type ORGANIZATION (the company filing the report) and
PRODUCT (any NEW product, service, or device the company announces it is
launching, introducing, releasing, or making available).

Rules:
- Only tag PRODUCT entities that are genuinely new product launches or releases.
- Do NOT tag earnings results, dividends, debt offerings, executive hires,
  acquisitions of other companies, or existing products merely mentioned.
- If there is no new product announcement, return an empty "products" list.
- Each description must be a single sentence under 180 characters.

Return ONLY valid JSON in exactly this shape:
{{
  "company_name": "<ORGANIZATION entity>",
  "products": [
    {{"new_product": "<PRODUCT entity>", "product_description": "<what it is / does>"}}
  ]
}}

FILING TEXT:
\"\"\"
{text}
\"\"\"
"""


def query_llm(text: str) -> dict:
    """Send filing text to Ollama and return the parsed JSON dict."""
    payload = {
        "model": MODEL,
        "prompt": PROMPT.format(text=text[:MAX_CHARS]),
        "stream": False,
        "format": "json",          # Ollama constrains output to valid JSON
        "options": {"temperature": 0, "num_ctx": NUM_CTX},  # deterministic, full context
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
    resp.raise_for_status()
    raw = resp.json()["response"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"company_name": "", "products": []}


def clean_description(desc: str) -> str:
    """Enforce the 180-character limit, cutting at a word boundary."""
    desc = " ".join(str(desc).split())
    if len(desc) <= MAX_DESC:
        return desc
    cut = desc[: MAX_DESC - 1]
    cut = cut[: cut.rfind(" ")] if " " in cut else cut
    return cut.rstrip(" ,;:") + "…"


def extract_products(text: str) -> tuple[str, list]:
    """
    Return (company_name, [ {new_product, product_description}, ... ]).
    Filters out junk entries the model sometimes produces.
    """
    result = query_llm(text)
    company = str(result.get("company_name", "")).strip()
    products = []
    for p in result.get("products", []) or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("new_product", "")).strip()
        desc = clean_description(p.get("product_description", ""))
        if name and name.lower() not in ("none", "n/a", "null") and desc:
            products.append({"new_product": name, "product_description": desc})
    return company, products


# ---------------------------------------------------------------------------
# Quick manual test:  python extract.py cache/<accession>.txt
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, time

    path = sys.argv[1]
    text = open(path, encoding="utf-8").read()
    print("keyword filter:", looks_like_product_announcement(text))
    t0 = time.time()
    company, products = extract_products(text)
    print(f"LLM took {time.time()-t0:.1f}s")
    print("company:", company)
    for p in products:
        print(f"  - {p['new_product']}: {p['product_description']}")
    if not products:
        print("  (no new products found)")
