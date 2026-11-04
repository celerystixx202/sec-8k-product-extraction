# Pulling New Product Launches Out of SEC 8-K Filings with a Local LLM

**Brendan Fuller**
**Code:** https://github.com/celerystixx202/sec-8k-product-extraction

## What I was trying to do

Every public company has to file an 8-K with the SEC when something material
happens: earnings, a new CEO, a big contract, or a product launch. Buried in
those filings is a steady stream of "we just launched X" announcements, but
nobody reads hundreds of 8-Ks by hand. The goal here was to build a Python
pipeline that pulls 8-Ks for S&P 500 companies, hands each one to a language
model running on my laptop, and gets back a clean table: company, ticker,
filing date, product name, and a one-line description under 180 characters.

## Where the data came from

I used two SEC endpoints, both free and both parsed with `requests` and
BeautifulSoup:

- `company_tickers.json` turns a ticker into the company's CIK number, which is
  how the SEC identifies filers. Apple's ticker AAPL maps to CIK 0000320193.
- The EDGAR browse feed, queried with that CIK and `type=8-K`, returns the
  company's most recent 8-Ks as an Atom feed with the filing date and a link
  to each filing's index page.

From the index page the code grabs the main 8-K document and, importantly,
every EX-99 exhibit attached to it. More on why that matters below.

The S&P 500 list itself, 503 tickers, came from the Wikipedia constituents
table. Tickers with a dot like BRK.B were swapped to BRK-B because that is how
the SEC writes them.

## How the pipeline works

**Step 1: clean the text.** Each filing is HTML. I strip the tags, drop
scripts and styles, and remove the hidden inline XBRL block at the top. That
block is machine-readable accounting metadata, and without removing it the
first thousand characters of every filing were tag soup. Cleaned text is
cached on disk so reruns are instant.

**Step 2: filter before paying the LLM cost.** Most 8-Ks have nothing to do
with products. They are earnings releases, debt deals, or board changes. A
quick regular expression looks for launch language: *launch*, *introduce*,
*unveil*, *now available*, *new product*, and so on. Only filings that match
go to the model. In the final run this filter threw out 81 percent of
filings, which is what made the whole thing fast enough to be practical.

**Step 3: let the model do the extraction.** The model is Llama 3.1 8B,
running locally through Ollama on an Apple M4 MacBook with 24 GB of RAM. No
paid API, no usage fees. The prompt tells the model to act as a Named Entity
Recognition system and tag two kinds of entities: the ORGANIZATION filing the
report, and any PRODUCT the company says it is launching or releasing. It
returns JSON in a fixed shape so Python can parse it every time.

Three settings made the difference between junk and usable output:

- Ollama's JSON mode, which forces the model to return valid JSON.
- Temperature zero, so the same filing always gives the same answer.
- A context window of 8,192 tokens. Ollama defaults to 2,048, which silently
  chops off most of each filing. The model only sees the tail and misses
  everything in the press release. Fixing this was the single biggest
  accuracy win in the project.

The prompt also tells the model what not to tag: earnings, dividends,
acquisitions, executive changes, or existing products that just get mentioned.
If there is no launch, it returns an empty list. Descriptions get trimmed to
180 characters at a word boundary as a final backstop.

**Step 4: write it out.** The main script walks the ticker list, pulls the ten
most recent 8-Ks per company, runs the filter and the model, and appends one
CSV row per product. A second log file records every filing it touched. The
script can be stopped and restarted without redoing work.

**Step 5: clean up.** An 8B model is good but not perfect. A short
post-processing script removes two kinds of noise: generic names that are not
real products, like "new transmission assets," and the same product showing up
twice because a quarterly earnings release re-listed a launch from the prior
quarter. The raw model output is kept alongside the cleaned file so both can
be inspected.

## What came out

| Metric | Value |
|---|---|
| Companies examined (S&P 500, alphabetical, MMM through BAX) | 58 |
| 8-K filings downloaded and parsed | 568 |
| Filings that passed the keyword filter and went to the LLM | 110 |
| Filings where the model found at least one product | 90 |
| Companies with at least one product | 29 |
| Raw product rows from the model | 360 |
| Rows after cleanup, in `new_products.csv` | 291 |
| Filing dates covered | May 2025 to Oct 2026 |
| Average model time per filing | 51 seconds |
| Total run time | 103 minutes |

Companies examined: MMM, AOS, ABT, ABBV, ACN, ADBE, AMD, AES, AFL, A, APD,
ABNB, AKAM, ALB, ARE, ALGN, ALLE, LNT, ALL, GOOGL, MO, AMZN, AMCR, AEE, AEP,
AXP, AIG, AMT, AWK, AMP, AME, AMGN, APH, ADI, AON, APA, APO, AAPL, AMAT, APP,
APTV, ACGL, ADM, ARES, ANET, AJG, AIZ, T, ATO, ADSK, ADP, AZO, AVY, AXON, BKR,
BALL, BAC, BAX.

The heavy hitters were Baker Hughes, Amazon, Amgen, AMD, and Airbnb. They all
attach long press releases to their quarterly 8-Ks with a "highlights" section
that reads like a product catalog. Banks, utilities, and insurers like Bank of
America, AEP, and AIG produced almost nothing, which is what you would expect.

A few rows from the output:

```
Apple Inc. | AAPL | 2025-10-30 | iPhone 17 Pro | Apple's high-end smartphone
AMD | AMD | 2026-08-04 | AMD Ryzen Embedded X100 Series | New embedded x86 processors for robotics and industrial automation
Axon | AXON | 2026-02-24 | Axon Vehicle Intelligence | AI-powered license plate recognition with a real-time operations platform
Amazon | AMZN | 2026-04-29 | Amazon Bio Discovery | An agentic AI application designed to accelerate drug discovery
Airbnb | ABNB | 2025-11-06 | Reserve Now, Pay Later | Lets guests pay $0 upfront when booking eligible domestic stays
```

## What went wrong along the way

**The product was never in the 8-K itself.** My first version only
downloaded the main 8-K document and found almost nothing. The 8-K cover is
usually a one-page form that says "see attached press release." The actual
announcement is in Exhibit 99.1. Once I started pulling the exhibits too, the
results went from empty to useful.

**Hidden XBRL noise.** Modern filings embed accounting tags in a hidden
header. Before I stripped it, the model was wasting its context window on
things like `us-gaap:CommonStockMember`.

**The default context window is a trap.** Ollama's 2,048-token default
truncates silently. Nothing errors, the model just reads the last page and
guesses. Raising it to 8,192 roughly doubled the time per filing but fixed
the accuracy.

**Earnings releases over-deliver.** A quarterly release often lists every
product launched that quarter, which is great, but the model sometimes also
tags a long-standing product that just gets mentioned in passing. Telling the
model what not to extract helped. A second validation pass with the model
would be the obvious next step.

**The SEC rate-limits you.** EDGAR requires a User-Agent header with your
name and email and occasionally throws a 503 under load. A short delay between
requests and retry with backoff handled it.

**It is slow.** An 8B model reading up to 5,000 tokens takes 30 to 50
seconds per filing. A hundred filings is well over an hour. The keyword
filter is the only reason scaling to the full S&P 500 is realistic.

## Where everything is

https://github.com/celerystixx202/sec-8k-product-extraction

- `main.py`, `sec_fetch.py`, `extract.py`, `postprocess.py` – the pipeline
- `new_products.csv` – the cleaned output, 291 rows
- `new_products_raw.csv` – the model's raw output before cleanup
- `run_log.csv` – every filing examined, with timing
- `README.md` – how to install and run it
