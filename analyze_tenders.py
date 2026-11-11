
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, format_datetime
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from xml.sax.saxutils import escape

SOURCES = [
    "https://dcr183.github.io/uk-contracts-inoreader/feed.xml",
    "https://dcr183.github.io/uk-contracts-inoreader/find_tender.xml",
]

OUTPUT = "best_opportunities.xml"

POSITIVE = {
    "cleaning": 15,
    "maintenance": 12,
    "repair": 12,
    "transport": 12,
    "logistics": 12,
    "delivery": 12,
    "printing": 15,
    "marketing": 12,
    "website": 10,
    "translation": 15,
    "grounds maintenance": 15,
    "waste collection": 10,
    "installation": 8,
    "supply": 8,
    "training": 7,
    "catering": 7,
}

COMPLEX = [
    "construction of", "major works", "clinical",
    "surgical", "nuclear", "defence weapons",
]

def fetch(url):
    request = Request(
        url,
        headers={"User-Agent": "UKTenderAnalyzer/1.0"}
    )
    with urlopen(request, timeout=25) as response:
        return response.read()

def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()

def extract_value(text):
    matches = re.findall(
        r"£\s*([\d,]+(?:\.\d{1,2})?)", text
    )
    amounts = [float(m.replace(",", "")) for m in matches]
    return amounts[0] if amounts else None

def score(title, description):
    combined = (title + " " + description).lower()
    points = 30
    reasons = []

    for keyword, bonus in POSITIVE.items():
        if keyword in combined:
            points += bonus
            reasons.append(keyword)

    for keyword in COMPLEX:
        if keyword in combined:
            points -= 20

    value = extract_value(combined)

    if value is not None:
        if 1000 <= value <= 25000:
            points += 25
            reasons.append("target contract value")
        elif value > 25000:
            points -= 20

    return max(0, min(100, points)), reasons, value

def get_text(item, tag):
    return clean(item.findtext(tag, default=""))

def collect():
    results = []
    seen = set()

    for source in SOURCES:
        try:
            root = ET.fromstring(fetch(source))
        except Exception as error:
            print(f"Could not read {source}: {error}")
            continue

        for item in root.findall(".//item"):
            title = get_text(item, "title")
            description = get_text(item, "description")
            link = get_text(item, "link")
            guid = get_text(item, "guid") or link

            if not title or not link:
                continue

            if urlparse(link).scheme not in ("http", "https"):
                continue

            identifier = link.rstrip("/").lower()
            if identifier in seen:
                continue
            seen.add(identifier)

            points, reasons, value = score(title, description)

            results.append({
                "title": title,
                "description": description,
                "link": link,
                "guid": guid,
                "score": points,
                "reasons": reasons,
                "value": value,
                "pubDate": get_text(item, "pubDate"),
            })

    return sorted(
        results,
        key=lambda item: item["score"],
        reverse=True
    )

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

    for item in items[:50]:
        reasons = ", ".join(item["reasons"]) or "General opportunity"
        value = (
            f"£{item['value']:,.2f}"
            if item["value"] is not None
            else "Not identified"
        )

        description = (
            f"Opportunity score: {item['score']}/100. "
            f"Estimated published value: {value}. "
            f"Matched categories: {reasons}. "
            f"{item['description']}"
        )

        lines.extend([
            "<item>",
            f"<title>{xml_text('[Score ' + str(item['score']) + '] ' + item['title'])}</title>",
            f"<link>{xml_text(item['link'])}</link>",
            f"<guid isPermaLink=\"false\">{xml_text(item['guid'])}</guid>",
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
    print(f"Analyzed {len(opportunities)} opportunities.")
    print(f"Created {OUTPUT}.")
