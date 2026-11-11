
import re
import hashlib
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime, format_datetime
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from xml.sax.saxutils import escape

SOURCES = [
    "https://dcr183.github.io/uk-contracts-inoreader/feed.xml",
    "https://dcr183.github.io/uk-contracts-inoreader/find_tender.xml",
]

OUTPUT = "best_opportunities.xml"
MIN_VALUE = 1000
MAX_VALUE = 25000
MAX_ITEMS = 100


GOOD_CATEGORIES = {
    # Easier to source from existing UK suppliers
    "cleaning": 25,
    "window cleaning": 25,
    "grounds maintenance": 24,
    "printing": 25,
    "translation": 22,
    "courier": 24,
    "parcel delivery": 24,
    "office supplies": 23,
    "stationery": 23,
    "graphic design": 22,
    "website maintenance": 22,
    "promotional materials": 22,
    "waste collection": 20,
    "pest control": 18,
    "equipment supply": 20,

    # Possible outsourcing, subject to qualifications
    "general maintenance": 17,
    "transport services": 17,
    "installation": 12,
    "catering": 12,
    "training": 10,

    # Specialist services: lower priority
    "engineering": 3,
    "consultancy": 3,
    "structural engineer": 2,
    "building services engineer": 2,
    "architectural": 2,
}


RISK_TERMS = {
    "security clearance": 20,
    "dbs check": 8,
    "clinical": 25,
    "medical": 18,
    "nuclear": 30,
    "asbestos": 20,
    "gas safe": 15,
    "electrical certification": 12,
    "professional indemnity": 8,
    "public liability insurance": 5,
    "iso 9001": 8,
    "iso 27001": 12,
    "construction of": 20,
    "major works": 20,    
    "structural engineer": 25,
    "building services engineer": 25,
    "specialist consultant": 20,
    "chartered engineer": 25,
    "heritage consultant": 18,
    "professional registration": 15,
}

DEADLINE_PATTERNS = [
    r"(?:closing date|closing deadline|submission deadline|"
    r"response deadline|tender deadline|deadline)\s*[:\-]?\s*"
    r"(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?)",
    r"(?:closing date|closing deadline|submission deadline|"
    r"response deadline|tender deadline|deadline)\s*[:\-]?\s*"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
]

def clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def fetch(url):
    request = Request(
        url,
        headers={"User-Agent": "UKTenderAnalyzer/2.0"}
    )
    with urlopen(request, timeout=30) as response:
        return response.read()

def get_text(item, tag):
    return clean(item.findtext(tag, default=""))


def extract_value(text):
    patterns = [
        r"(?:advertised value|estimated value|contract value|total value|estimated contract value|value excluding vat|value including vat)\s*[:\-]?\s*(?:£|GBP)\s*([\d,]+(?:\.\d{1,2})?)",
        r"(?:£|GBP)\s*([\d,]+(?:\.\d{1,2})?)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.I)
        if matches:
            try:
                return float(matches[0].replace(",", ""))
            except ValueError:
                pass
    return None


def parse_deadline(text):
    for pattern in DEADLINE_PATTERNS:
        match = re.search(pattern, text, re.I)
        if not match:
            continue

        raw = match.group(1).strip()

        try:
            if re.match(r"^\d{4}-", raw):
                dt = datetime.fromisoformat(
                    raw.replace("Z", "+00:00")
                )
            else:
                dt = None
                for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        dt = datetime.strptime(raw, fmt)
                        break
                    except ValueError:
                        continue

                if dt is None:
                    continue

                # Date-only deadlines are treated as
                # end-of-day, pending official verification.
                dt = dt.replace(
                    hour=23, minute=59, second=59
                )

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(timezone.utc)

        except ValueError:
            continue

    return None

def score_opportunity(title, description):
    combined = (title + " " + description).lower()
    now = datetime.now(timezone.utc)

    value = extract_value(description)
    deadline = parse_deadline(description)

    # Never present a known expired tender as open.
    if deadline and deadline < now:
        return None

    # Exclude clearly out-of-range values.
    if value is not None:
        if not MIN_VALUE <= value <= MAX_VALUE:
            return None

    points = 35
    reasons = []
    risks = []

    matched = [
        (word, bonus)
        for word, bonus in GOOD_CATEGORIES.items()
        if word in combined
    ]

    if matched:
        matched.sort(key=lambda x: x[1], reverse=True)
        points += min(sum(x[1] for x in matched[:2]), 30)
        reasons.extend(x[0] for x in matched[:2])

    if value is not None:
        points += 25
        reasons.append("value within target range")
    else:
        risks.append("contract value not verified")

    if deadline:
        days_left = (
            deadline - now
        ).total_seconds() / 86400

        if days_left >= 7:
            points += 10
            reasons.append("at least 7 days remaining")
        elif days_left < 2:
            points -= 15
            risks.append("urgent submission deadline")
    else:
        risks.append("deadline not verified")

    for term, penalty in RISK_TERMS.items():
        if term in combined:
            points -= penalty
            risks.append(term)

    if any(word in combined for word in (
        "subcontract", "sub-contract",
        "supply and delivery", "framework supplier"
    )):
        points += 5
        reasons.append("possible supplier opportunity")

    # Missing key details prevent a high-confidence alert.
    if value is None or deadline is None:
        points = min(points, 69)

    points = max(0, min(100, points))

    return {
        "score": points,
        "value": value,
        "deadline": deadline,
        "reasons": reasons,
        "risks": risks,
    }

def collect():
    results = []
    seen = set()
    successful_sources = 0

    for source in SOURCES:
        try:
            root = ET.fromstring(fetch(source))
            successful_sources += 1
        except Exception as error:
            print(f"ERROR reading {source}: {error}")
            continue

        for item in root.findall(".//item"):
            title = get_text(item, "title")
            description = get_text(item, "description")
            link = get_text(item, "link")

            if not title or not link:
                continue

            if urlparse(link).scheme not in ("http", "https"):
                continue

            identifier = link.rstrip("/").lower()

            if identifier in seen:
                continue

            analysis = score_opportunity(
                title, description
            )

            if analysis is None:
                continue

            seen.add(identifier)

            guid = get_text(item, "guid") or link

            results.append({
                "title": title,
                "description": description,
                "link": link,
                "guid": guid,
                "pubDate": get_text(item, "pubDate"),
                **analysis,
            })

    # Avoid replacing a working feed with empty output
    # when all source downloads fail.
    if successful_sources == 0:
        raise RuntimeError(
            "All source feeds failed. Existing RSS preserved."
        )

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return results

def xml_text(value):
    return escape(str(value), {'"': "&quot;"})

def create_feed(items):
    now = format_datetime(datetime.now(timezone.utc))

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        '<channel>',
        '<title>UK Best Business Opportunities</title>',
        '<link>https://dcr183.github.io/uk-contracts-inoreader/</link>',
        '<description>Ranked UK tender opportunities</description>',
        f'<lastBuildDate>{now}</lastBuildDate>',
    ]

    for item in items[:MAX_ITEMS]:
        value = (
            f"£{item['value']:,.2f}"
            if item["value"] is not None
            else "Unverified"
        )

        deadline = (
            item["deadline"].strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            if item["deadline"]
            else "Unverified"
        )

        reasons = ", ".join(item["reasons"]) or "None"
        risks = ", ".join(item["risks"]) or "None"

        description = (
            f"Opportunity score: {item['score']}/100. "
            f"Contract value: {value}. "
            f"Deadline: {deadline}. "
            f"Positive indicators: {reasons}. "
            f"Risks/checks required: {risks}. "
            f"Original notice: {item['link']}. "
            f"{item['description']}"
        )

        # Stable identifiers prevent duplicate alerts
        # whenever the ranking changes.
        stable_id = hashlib.sha256(
          (item["link"] + "|score-v2|" + str(item["score"])).encode("utf-8")
        ).hexdigest()[:24]

        lines.extend([
            "<item>",
            f"<title>{xml_text('[Score ' + str(item['score']) + '] ' + item['title'])}</title>",
            f"<link>{xml_text(item['link'])}</link>",
            f'<guid isPermaLink="false">ukranked-{stable_id}</guid>',
            f"<description>{xml_text(description)}</description>",
            f"<pubDate>{xml_text(item['pubDate'] or now)}</pubDate>",
            "</item>",
        ])

    lines.extend(["</channel>", "</rss>"])

    with open(OUTPUT, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))

if __name__ == "__main__":
    opportunities = collect()
    create_feed(opportunities)

    high_priority = sum(
        1 for item in opportunities
        if item["score"] >= 70
    )

    print(f"Eligible opportunities: {len(opportunities)}")
    print(f"High-priority opportunities: {high_priority}")
    print(f"Generated: {OUTPUT}")
