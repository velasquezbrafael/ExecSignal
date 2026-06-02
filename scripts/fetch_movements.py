#!/usr/bin/env python3
"""
ExecSignal — EDGAR 8-K / Item 5.02 pipeline
Runs in GitHub Actions every 4 hours.

Steps:
  1. Fetch recent 8-K filings mentioning Item 5.02 from EDGAR
  2. Extract Item 5.02 text from each filing document
  3. Parse with Claude Haiku → structured movement records
  4. Filter noise + low-confidence records
  5. Dedup against existing data/movements.json
  6. Assign recruiter signal level
  7. Write updated data/movements.json
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import requests
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DATA_PATH = Path(__file__).parent.parent / "data" / "movements.json"
MAX_FILINGS = 50
MIN_SECTION_LEN = 150
MAX_SECTION_LEN = 3000
MIN_CONFIDENCE = 0.70
REQUEST_DELAY = 0.4  # seconds between EDGAR requests

HEADERS = {
    "User-Agent": "ExecSignal research@execsignal.io",
    "Accept-Encoding": "gzip, deflate",
}

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------

class _Stripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return " ".join(self.parts)


def strip_html(html: str) -> str:
    s = _Stripper()
    try:
        s.feed(html)
    except Exception:
        pass
    return re.sub(r"\s+", " ", s.get_text()).strip()


# ---------------------------------------------------------------------------
# STEP 1 — Fetch EDGAR filings
# ---------------------------------------------------------------------------

def fetch_edgar_hits() -> list[dict]:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=25)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": '"Item 5.02"',
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": start,
        "enddt": end,
    }

    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    hits = data.get("hits", {}).get("hits", [])
    print(f"EDGAR returned {len(hits)} hits ({start} → {end})")
    return hits


def parse_display_name(display_names: list) -> tuple[str, str | None]:
    """Extract company name and ticker from display_names list."""
    if not display_names:
        return "Unknown", None
    raw = display_names[0]
    # Format: "Company Name (TICKER) (CIK XXXXXXXXXX)"
    ticker_match = re.search(r"\(([A-Z]{1,5})\)", raw)
    ticker = ticker_match.group(1) if ticker_match else None
    # Remove all parenthetical groups to get the company name
    name = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    return name or "Unknown", ticker


def build_urls(ciks: list, adsh: str) -> tuple[str, str]:
    """Return (index_url, base_url) for a filing."""
    cik_int = int(ciks[0])
    adsh_no_dashes = adsh.replace("-", "")
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{adsh_no_dashes}/{adsh}-index.htm"
    )
    base_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int}/{adsh_no_dashes}/"
    )
    return index_url, base_url


# ---------------------------------------------------------------------------
# STEP 2 — Fetch Item 5.02 text from each filing
# ---------------------------------------------------------------------------

def get_primary_doc_filename(index_html: str) -> str | None:
    """Find the filename of the primary 8-K document from the index page."""
    # Look for a table row where Type column is exactly "8-K"
    pattern = re.compile(
        r'<tr[^>]*>.*?<td[^>]*>\s*8-K\s*</td>.*?href="([^"]+)"',
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(index_html)
    if m:
        href = m.group(1)
        return href.split("/")[-1]

    # Fallback: look for .htm files in the index
    links = re.findall(r'href="([^"]*\.htm)"', index_html, re.IGNORECASE)
    for link in links:
        fname = link.split("/")[-1].lower()
        if not fname.endswith("-index.htm") and fname != "":
            return link.split("/")[-1]
    return None


def extract_item_502_text(plain_text: str) -> str | None:
    """Extract Item 5.02 section from plain text. Returns None if too short."""
    # Find "Item 5.02" (case-insensitive)
    pos = plain_text.lower().find("item 5.02")
    if pos == -1:
        return None

    section = plain_text[pos:]

    # Find next Item header after the first "Item 5.02"
    # Look for something like "Item 5.03", "Item 6.01", etc.
    next_item = re.search(r"Item\s+[5-9]\.\d+", section[10:], re.IGNORECASE)
    if next_item:
        section = section[: 10 + next_item.start()]

    section = section[:MAX_SECTION_LEN].strip()

    if len(section) < MIN_SECTION_LEN:
        return None

    return section


def fetch_item_502(hit: dict) -> tuple[dict, str | None]:
    """Given an EDGAR hit, return (metadata_dict, item_502_text)."""
    src = hit.get("_source", {})
    display_names = src.get("display_names", [])
    adsh = src.get("adsh", "")
    file_date = src.get("file_date", "")
    ciks = src.get("ciks", ["0"])

    company, ticker = parse_display_name(display_names)
    index_url, base_url = build_urls(ciks, adsh)

    metadata = {
        "adsh": adsh,
        "company": company,
        "ticker": ticker,
        "filed_date": file_date[:10] if file_date else "",
        "cik": ciks[0] if ciks else "",
        "source_url": index_url,
    }

    try:
        time.sleep(REQUEST_DELAY)
        r = requests.get(index_url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        index_html = r.text

        filename = get_primary_doc_filename(index_html)
        if not filename:
            return metadata, None

        doc_url = base_url + filename
        metadata["source_url"] = doc_url

        time.sleep(REQUEST_DELAY)
        r2 = requests.get(doc_url, headers=HEADERS, timeout=20)
        r2.raise_for_status()
        plain = strip_html(r2.text)

        section = extract_item_502_text(plain)
        return metadata, section

    except Exception as e:
        print(f"  Warning: could not fetch {adsh}: {e}")
        return metadata, None


# ---------------------------------------------------------------------------
# STEP 3 — Parse with Claude Haiku
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = "You parse SEC 8-K filings and return structured JSON only. No markdown."

USER_TEMPLATE = """Parse this SEC 8-K Item 5.02 text and return a JSON array.
Each element represents one executive event mentioned.

Fields per event:
- executive_name: string or null
- role: string (full title) or null
- movement_type: "departure"|"appointment"|"retirement"|"transition"|"interim"|"noise"
  Use "noise" ONLY if the ENTIRE section is about equity plan amendments,
  director elections, or comp program changes with zero named individual
  executive departure or appointment.
- effective_date: "YYYY-MM-DD" or null
- reason: context string max 120 chars or null
- successor: successor name if mentioned or null
- prior_company: prior company if mentioned (for appointments) or null
- confidence: float 0.0-1.0

Return ONLY a valid JSON array. Example: [{...}, {...}]
If the entire section is noise, return: [{{"movement_type":"noise","confidence":0.95,...nulls}}]

Text:
{text}"""


def parse_with_haiku(item_502_text: str) -> list[dict]:
    """Send Item 5.02 text to Claude Haiku. Returns list of event dicts."""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": USER_TEMPLATE.format(text=item_502_text)}
            ],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown fences if model adds them despite instructions
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        return []
    except json.JSONDecodeError as e:
        print(f"  JSON parse error from Haiku: {e} — skipping")
        return []
    except Exception as e:
        print(f"  Haiku error: {e} — skipping")
        return []


# ---------------------------------------------------------------------------
# STEP 4 — Filter
# ---------------------------------------------------------------------------

def should_keep(event: dict) -> bool:
    mt = event.get("movement_type", "noise")
    conf = event.get("confidence", 0)
    name = event.get("executive_name")

    if mt == "noise":
        return False
    if conf < MIN_CONFIDENCE:
        return False
    if not name and mt not in ("noise",):
        return False
    return True


# ---------------------------------------------------------------------------
# STEP 5 — Dedup
# ---------------------------------------------------------------------------

def is_duplicate(new_rec: dict, existing: list[dict]) -> bool:
    try:
        new_date = datetime.strptime(new_rec.get("filed_date", ""), "%Y-%m-%d")
    except ValueError:
        new_date = None

    for ex in existing:
        name_match = (
            (new_rec.get("executive_name") or "").lower()
            == (ex.get("executive_name") or "").lower()
        )
        co_match = (
            (new_rec.get("company") or "").lower()
            == (ex.get("company") or "").lower()
        )
        type_match = new_rec.get("movement_type") == ex.get("movement_type")

        if name_match and co_match and type_match:
            if new_date is None:
                return True
            try:
                ex_date = datetime.strptime(ex.get("filed_date", ""), "%Y-%m-%d")
                if abs((new_date - ex_date).days) <= 7:
                    return True
            except ValueError:
                return True

    return False


# ---------------------------------------------------------------------------
# STEP 6 — Assign signal
# ---------------------------------------------------------------------------

def assign_signal(event: dict) -> str:
    mt = event.get("movement_type", "")
    successor = event.get("successor")

    if mt in ("departure", "interim"):
        return "high"
    if mt == "retirement" and not successor:
        return "medium"
    if mt in ("appointment", "transition") or (mt == "retirement" and successor):
        return "low"
    return "none"


# ---------------------------------------------------------------------------
# STEP 7 — Load / write data/movements.json
# ---------------------------------------------------------------------------

def load_existing() -> dict:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text())
        except Exception:
            pass
    return {"updated_at": "", "total_filings_checked": 0, "movements": []}


def drop_old(movements: list[dict], days: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for m in movements:
        try:
            d = datetime.strptime(m.get("filed_date", ""), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if d >= cutoff:
                out.append(m)
        except ValueError:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== ExecSignal EDGAR pipeline ===")

    # Load existing data
    existing_data = load_existing()
    existing_movements = existing_data.get("movements", [])
    prev_filings_checked = existing_data.get("total_filings_checked", 0)

    # Step 1
    hits = fetch_edgar_hits()
    hits = hits[:MAX_FILINGS]

    new_movements = []
    filings_checked = 0

    for i, hit in enumerate(hits):
        src = hit.get("_source", {})
        adsh = src.get("adsh", f"unknown-{i}")
        print(f"[{i+1}/{len(hits)}] {adsh}")

        metadata, section = fetch_item_502(hit)
        filings_checked += 1

        if not section:
            print("  -> no Item 5.02 section found, skipping")
            continue

        # Step 3
        events = parse_with_haiku(section)
        print(f"  -> Haiku returned {len(events)} event(s)")

        for j, event in enumerate(events):
            # Merge metadata into record
            record = {
                "id": f"{adsh}-{j}",
                "filed_date": metadata["filed_date"],
                "company": metadata["company"],
                "ticker": metadata["ticker"],
                "executive_name": event.get("executive_name"),
                "role": event.get("role"),
                "movement_type": event.get("movement_type", "noise"),
                "effective_date": event.get("effective_date"),
                "reason": event.get("reason"),
                "successor": event.get("successor"),
                "prior_company": event.get("prior_company"),
                "confidence": event.get("confidence", 0),
                "signal": "none",
                "source_url": metadata["source_url"],
            }

            # Step 4 — filter
            if not should_keep(record):
                print(f"  -> dropped (type={record['movement_type']}, conf={record['confidence']:.2f})")
                continue

            # Step 5 — dedup
            if is_duplicate(record, existing_movements + new_movements):
                print(f"  -> duplicate, skipping")
                continue

            # Step 6 — signal
            record["signal"] = assign_signal(record)
            new_movements.append(record)
            print(f"  -> kept: {record['executive_name']} / {record['movement_type']} / signal={record['signal']}")

    # Step 7 — merge + write
    all_movements = new_movements + existing_movements
    all_movements = drop_old(all_movements)
    all_movements.sort(key=lambda m: m.get("filed_date", ""), reverse=True)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_filings_checked": prev_filings_checked + filings_checked,
        "movements": all_movements,
    }

    DATA_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(
        f"\nChecked {filings_checked} filings, "
        f"found {len(new_movements)} movements after filtering, "
        f"total {len(all_movements)} in feed"
    )


if __name__ == "__main__":
    main()
