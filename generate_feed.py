
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

BASE = "https://www.contractsfinder.service.gov.uk/"
API = BASE + "Published/Notices/OCDS/Search?limit=100"
OUTPUT = "feed.xml"
MAX_PAGES = 5

def parse_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    except ValueError:
        return None

def fetch_pages():
    url = API
    seen_urls = set()
    releases = []

    for page in range(MAX_PAGES):
        if not url or url in seen_urls:
            break

        if not url.startswith(
            BASE + "Published/Notices/OCDS/Search?"
        ):
            raise ValueError("Unexpected pagination URL")

        seen_urls.add(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "UKContractsRSS/1.0"}
        )

        with urllib.request.urlopen(
            request, timeout=45
        ) as response:
            data = json.load(response)

        batch = data.get("releases", [])
        releases.extend(batch)
        print(f"Page {page + 1}: {len(batch)} releases")

        url = (data.get("links") or {}).get("next")

    return releases

def collect_notices(releases):
    results = {}
    now = datetime.now(timezone.utc)

    for release in releases:
        tender = release.get("tender") or {}
        value = tender.get("value") or {}

        try:
            amount = float(value.get("amount"))
        except (TypeError, ValueError):
            continue

        if not 1000 <= amount <= 25000:
            continue

        if value.get("currency", "GBP") != "GBP":
            continue

        # Keep only tender opportunities.
        if release.get("initiationType") != "tender":
            continue

        if release.get("awards") or release.get("contracts"):
            continue

        status = (tender.get("status") or "").lower()
        if status != "active":
            continue

        deadline = (
            (tender.get("tenderPeriod") or {}).get("endDate")
        )
        deadline_date = parse_date(deadline)

        # Only accept notices with a future deadline.
        if deadline_date is None or deadline_date <= now:
            continue

        identifier = (
            release.get("ocid") or release.get("id")
        )
        if not identifier:
            continue

        title = tender.get("title") or "Untitled contract"
        description = tender.get("description") or ""

                url = next(
            (
                doc["url"]
                for doc in release.get("planning", {}).get("documents", [])
                if doc.get("url")
                and "/Notice/" in doc["url"]
            ),
            BASE + "Search?searchTerm=" + urllib.parse.quote(title)
        )

        results[identifier] = {
            "title": title,
            "description": description,
            "amount": amount,
            "id": identifier,
            "url": url,
            "date": release.get("date"),
            "deadline": deadline
        }

    return list(results.values())

def build_feed(notices):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = (
        "UK Contracts Finder Opportunities"
    )
    ET.SubElement(channel, "link").text = BASE
    ET.SubElement(channel, "description").text = (
        "UK active tenders valued GBP 1,000 to 25,000"
    )

    for notice in notices:
        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = notice["title"]
        ET.SubElement(item, "link").text = notice["url"]
        ET.SubElement(
            item, "guid", isPermaLink="false"
        ).text = notice["id"]

        details = (
            f'Advertised value: GBP {notice["amount"]:,.0f}\n'
            f'Status: active\n'
            f'Deadline: {notice["deadline"]}\n\n'
            + notice["description"]
        )

        ET.SubElement(
            item, "description"
        ).text = details

        published = parse_date(notice["date"])
        if published:
            ET.SubElement(
                item, "pubDate"
            ).text = format_datetime(published)

    ET.indent(rss)
    ET.ElementTree(rss).write(
        OUTPUT,
        encoding="utf-8",
        xml_declaration=True
    )

if __name__ == "__main__":
    releases = fetch_pages()
    notices = collect_notices(releases)
    build_feed(notices)
    print(f"Generated RSS with {len(notices)} notices")
