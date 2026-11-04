# SEC 8-K New Product Extraction with a Local LLM

Extracts new product announcements from SEC Form 8-K filings of S&P 500
companies using a locally hosted large language model (Llama 3.1 8B via
Ollama), and writes the results to a CSV.

## Output format

`new_products.csv`

| company_name | stock_name | filing_time | new_product | product_description |
|---|---|---|---|---|
| NVIDIA Corporation | NVDA | 2026-08-26 | NVIDIA Cosmos 3 | Fully open frontier omnimodel for physical AI |

`run_log.csv` records every filing examined (ticker, accession number, size,
whether it passed the keyword filter, LLM time, number of products found) and
is the source of the statistics in the report.

## How it works

1. **sec_fetch.py** – maps tickers to CIKs using `company_tickers.json`,
   reads each company's 8-K Atom feed from EDGAR, downloads the primary
   document plus any EX-99 press-release exhibits, and strips the HTML to
   plain text. Filings are cached in `cache/` so reruns are instant.
2. **extract.py** – a cheap regex keyword filter drops filings with no
   product-launch language (earnings, debt, board changes). Filings that pass
   are sent to Llama 3.1 8B with a Named Entity Recognition prompt that tags
   ORGANIZATION and PRODUCT entities and returns strict JSON. Descriptions are
   trimmed to the 180-character limit.
3. **main.py** – loops over `sp500_tickers.txt`, runs the two steps above,
   and appends rows to the CSVs. It is resumable: rerunning skips filings
   already in `run_log.csv`.
4. **postprocess.py** – removes duplicate products reported in more than one
   filing and generic non-products, keeping the raw model output in
   `new_products_raw.csv` and writing the cleaned `new_products.csv`.

## Setup

```bash
# 1. Install Ollama from https://ollama.com and pull the model
ollama pull llama3.1:8b

# 2. Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Set your SEC User-Agent (required by sec.gov)
export SEC_USER_AGENT="Your Name your@email.com"
```

## Run

```bash
python main.py                          # 100 filings from the S&P 500 list
python main.py --max-filings 300        # more filings
python main.py --tickers NVDA TSLA AMD  # specific companies
python postprocess.py                   # dedupe and clean -> new_products.csv
```

Test individual pieces:

```bash
python sec_fetch.py AAPL                 # fetch and print recent 8-Ks
python extract.py cache/<accession>.txt  # run the LLM on one cached filing
```

## Files

- `main.py` – end-to-end pipeline
- `sec_fetch.py` – SEC EDGAR download and HTML cleaning
- `extract.py` – keyword filter and LLM extraction
- `sp500_tickers.txt` – S&P 500 constituents (from Wikipedia)
- `postprocess.py` – dedupe and cleanup
- `new_products.csv` – structured output (cleaned)
- `new_products_raw.csv` – raw LLM output before cleanup
- `run_log.csv` – per-filing processing log
- `report.md` – methodology report (`Assign 2 LLM Brendan Fuller CAP 2026.docx` is the same report as a Word document)
