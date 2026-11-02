# Extracting New Product Announcements from SEC 8-K Filings with a Local LLM

**Author:** Brendan Fuller
**GitHub:** https://github.com/celerystixx202/sec-8k-product-extraction

## 1. Objective

Form 8-K is the "current report" public companies file with the SEC when a
material event occurs. A fraction of these announce new products. The goal of
this project was to build a Python pipeline that downloads 8-K filings for
S&P 500 companies, uses a large language model to identify new product
announcements, and writes the results to a CSV with five columns:
`company_name, stock_name, filing_time, new_product, product_description`.

## 2. Data Source

Two SEC endpoints were used, parsed with `requests` and BeautifulSoup:

- `https://www.sec.gov/files/company_tickers.json` maps a ticker symbol to
  the company's Central Index Key (CIK), e.g. AAPL to 0000320193.
- `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&count={n}&output=atom`
  returns an Atom feed of the company's most recent 8-K filings, each with a
  filing date, accession number, and a link to the filing's index page.

From the index page the script downloads the primary 8-K document **and every
EX-99 exhibit**. This turned out to be essential: the 8-K cover document is
usually a one-page form that only says "see attached press release", while the
actual product description lives in Exhibit 99.1.

The S&P 500 ticker list (503 symbols) was taken from the Wikipedia
constituents table. Tickers with a period (BRK.B) were rewritten with a hyphen
(BRK-B) to match the SEC's convention.

## 3. Methodology

### 3.1 Preprocessing

Each downloaded HTML document is converted to plain text with BeautifulSoup.
Scripts, styles, and the hidden inline-XBRL header block (`<ix:header>`) are
removed, since the latter injects hundreds of accounting tags at the top of
the text that would waste the model's context window. Whitespace is collapsed.
Cleaned text is cached on disk by accession number so the pipeline can be
rerun without re-downloading.

### 3.2 Keyword pre-filter

Most 8-Ks report earnings, debt offerings, or executive changes. Sending all
of them to the LLM would waste most of the run time. A regular expression
checks for product-launch language (*launch*, *introduce*, *unveil*, *now
available*, *new product*, *general availability*, etc.). Only filings that
match are sent to the model. In the final run, 81% of filings were
dropped by this filter.

### 3.3 LLM extraction with a Named Entity Recognition prompt

The LLM is **Llama 3.1 8B** (`llama3.1:8b`, 4.9 GB, Q4 quantization), served
locally by Ollama on an Apple M4 MacBook with 24 GB of RAM. No paid API was
used.

The prompt instructs the model to act as a Named Entity Recognition system
tagging two entity types, **ORGANIZATION** (the filing company) and
**PRODUCT** (a newly announced product), and to return strict JSON:

```json
{"company_name": "...", "products": [{"new_product": "...", "product_description": "..."}]}
```

Three settings matter for reliability:

- `format: "json"` makes Ollama constrain the output to valid JSON, so Python
  can parse it with `json.loads` every time.
- `temperature: 0` makes the extraction deterministic.
- `num_ctx: 8192` raises Ollama's context window from its default of 2,048
  tokens. Without this the model silently sees only the tail of each filing.
  Up to 20,000 characters of filing text are passed.

The prompt explicitly tells the model not to tag earnings, dividends,
acquisitions, executive changes, or existing products merely mentioned, and
to return an empty list when there is no launch. Descriptions are trimmed to
180 characters at a word boundary as a final safeguard.

### 3.4 Pipeline and output

`main.py` iterates through the ticker list, pulls the 10 most recent 8-Ks per
company, applies the filter, calls the model, and appends one CSV row per
product found. A second file, `run_log.csv`, records every filing examined
with its size, filter result, and LLM latency. The run is resumable.

### 3.5 Post-processing

`postprocess.py` applies two cleanup rules to the raw model output and keeps
the raw file alongside the cleaned one. First, generic names that are not
specific products ("new transmission assets", "Duralast branded products")
are dropped with a short regular-expression blocklist (13 rows). Second, the
same product reported by the same company in more than one filing, which
happens when a quarterly earnings release re-lists a launch from the previous
quarter, is kept only once at its earliest filing date (56 rows).

## 4. Results

| Metric | Value |
|---|---|
| Companies examined (S&P 500, alphabetical from MMM to BAX) | 58 |
| 8-K filings downloaded and parsed | 568 |
| Filings passing keyword filter (sent to LLM) | 110 |
| Filings where the LLM found at least one product | 90 |
| Companies with at least one product | 29 |
| Raw product rows from the LLM (`new_products_raw.csv`) | 360 |
| Rows after dedupe and cleanup (`new_products.csv`) | 291 |
| Filing dates covered | 2025-05-01 to 2026-10-29 |
| Mean LLM time per filing | 51.2 s |
| Total run time (download + LLM) | 102.6 min |

Companies examined: MMM, AOS, ABT, ABBV, ACN, ADBE, AMD, AES, AFL, A, APD,
ABNB, AKAM, ALB, ARE, ALGN, ALLE, LNT, ALL, GOOGL, MO, AMZN, AMCR, AEE, AEP,
AXP, AIG, AMT, AWK, AMP, AME, AMGN, APH, ADI, AON, APA, APO, AAPL, AMAT, APP,
APTV, ACGL, ADM, ARES, ANET, AJG, AIZ, T, ATO, ADSK, ADP, AZO, AVY, AXON, BKR,
BALL, BAC, BAX.

The companies with the most products were Baker Hughes (BKR), Amazon (AMZN),
Amgen (AMGN), AMD, and Airbnb (ABNB), all of which attach long press releases
listing product launches to their quarterly 8-Ks. Banks, utilities, and
insurers (BAC, AEP, AIG) produced few or none, as expected.

Sample output:

```
company_name | stock_name | filing_time | new_product | product_description
Apple Inc. | AAPL | 2025-07-31 | Apple Vision Pro | a new software design that extends across all of our platforms…
Apple Inc. | AAPL | 2025-10-30 | iPhone 17 Pro | Apple's high-end smartphone…
Advanced Micro Devices, Inc. | AMD | 2026-02-03 | AMD FSR 'Redstone' | machine-learning based features delivering more immersive visuals for …
Advanced Micro Devices, Inc. | AMD | 2026-02-03 | AMD Ryzen 7 9850X3D | fastest gaming processor, powered by the 'Zen 5' architecture and AMD …
AMAZON.COM, INC. | AMZN | 2026-04-14 | Amazon Leo | Amazon's low Earth orbit satellite network, delivering fast, reliable …
AMAZON.COM, INC. | AMZN | 2026-04-14 | Amazon Leo Direct-to-Device (D2D) system | allows Amazon to deliver more advanced voice, data, and messaging serv…
Arista Networks, Inc. | ANET | 2025-05-06 | Cluster Load Balancing (CLB) | maximizes AI workload performance with consistent, low-latency network…
Arista Networks, Inc. | ANET | 2025-05-06 | Arista CloudVision Universal Network Observability (CV UNO) | offers AI job-centric observability for enhanced troubleshooting and r…
Axon Enterprise, Inc. | AXON | 2026-02-24 | Axon 911 | AI-enabled 911 call handling with modernized communications, precise l…
Axon Enterprise, Inc. | AXON | 2026-02-24 | Axon Vehicle Intelligence | AI-powered automatic license plate recognition (ALPR) solution with re…
```

## 5. Challenges

**The product is not in the 8-K itself.** The first version only downloaded
the primary document and found almost nothing, because the announcement is in
the attached press release. Fetching EX-99 exhibits fixed this.

**Inline XBRL noise.** Modern filings embed machine-readable tags in a hidden
header. Before stripping it, the first thousand characters of every filing
were accounting codes.

**Ollama's default context window.** The default of 2,048 tokens truncates
filings silently. Raising `num_ctx` was the single biggest accuracy
improvement, at the cost of roughly doubling latency.

**Over-extraction from earnings releases.** Earnings press releases often
contain a paragraph of "business highlights" listing products launched during
the quarter. The model correctly extracts those, but it sometimes also tags a
long-standing product mentioned in passing (e.g. an existing energy-storage
product). The prompt's negative instructions reduced but did not eliminate
this; a second validation pass with the model would be a natural next step.

**SEC rate limits.** EDGAR requires a User-Agent header identifying the
requester and occasionally returns HTTP 503 under load. A 150 ms delay
between requests and retry with exponential backoff handled this.

**Speed.** At ~30-45 seconds per filing for an 8B model reading up to 5,000
tokens, 100 filings takes about an hour. The keyword filter is what makes
scaling to the full S&P 500 feasible.

## 6. Repository

Code, CSV output, and this report are at
https://github.com/celerystixx202/sec-8k-product-extraction

- `main.py`, `sec_fetch.py`, `extract.py` – pipeline
- `new_products.csv` – structured output
- `run_log.csv` – per-filing processing log
- `README.md` – setup and run instructions
