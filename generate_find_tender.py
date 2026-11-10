import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
OUTPUT = "find_tender.xml"
MIN_VALUE = 1000
MAX_VALUE = 25000
MAX_PAGES = 50
PAGE_SIZE = 100

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def parse_date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def eligible_amounts(tender):
    candidates = [tender.get("value")]
    candidates.extend(lot.get("value") for lot in (tender.get("lots") or []))
    for value in candidates:
        if not isinstance(value, dict):
            continue
        if str(value.get("currency", "GBP")).upper() != "GBP":
            continue
        try:
            amount = float(value["amount"])
        except (KeyError, ValueError, TypeError):
            continue
        if MIN_VALUE <= amount <= MAX_VALUE:
            yield amount



def notice_link(release):
    base = "https://www.find-tender.service.gov.uk"

    documents = (
        (release.get("documents") or [])
        + ((release.get("tender") or {}).get("documents") or [])
    )

    for doc in documents:
        url = doc.get("url", "")
        parsed = urllib.parse.urlparse(url)

        if (
            parsed.scheme == "https"
            and parsed.hostname == "www.find-tender.service.gov.uk"
            and parsed.path.lower().startswith("/notice/")
            and "/attachment/" not in parsed.path.lower()
        ):
            return url

    ocid = release.get("ocid", "")
    return (
        base + "/Search/Results?keywords="
        + urllib.parse.quote(ocid)
    )


def fetch_notices():
    notices = {}
    cursor = None
    stats = {"releases": 0, "active": 0, "priced": 0, "open": 0}
    now = datetime.now(timezone.utc)

    for page in range(MAX_PAGES):
        params = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        request = urllib.request.Request(
            API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": "UKTenderRSS/2.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logging.error("API request failed on page %s: %s", page + 1, exc)
            if page == 0:
                raise
            break

        releases = data.get("releases") or []
        if not releases:
            break
        for release in releases:
            stats["releases"] += 1
            tender = release.get("tender") or {}
            if str(tender.get("status", "")).lower() != "active":
                continue
            stats["active"] += 1
            amounts = list(eligible_amounts(tender))
            if not amounts:
                continue
            stats["priced"] += 1
            deadline = (tender.get("tenderPeriod") or {}).get("endDate")
            closing = parse_date(deadline)
            if closing is None or closing <= now:
                continue
            stats["open"] += 1
            identifier = release.get("ocid") or release.get("id")
            if not identifier:
                continue
            title = tender.get("title") or "Untitled tender"
            notices[identifier] = {
                "title": title,
                "description": tender.get("description") or "",
                "amount": min(amounts),
                "deadline": deadline,
                "url": notice_link(release),
                "id": identifier,
                "published": parse_date(release.get("date")) or now,
            }
        cursor = data.get("nextCursor")
        logging.info("Page %s: examined %s releases; found %s eligible notices", page + 1, stats["releases"], len(notices))
        if not cursor:
            break

    logging.info("Totals: %s; unique eligible notices: %s", stats, len(notices))
    return sorted(notices.values(), key=lambda n: n["published"], reverse=True)


def generate_feed(notices):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "UK Find a Tender Opportunities"
    ET.SubElement(channel, "link").text = "https://www.find-tender.service.gov.uk/"
    ET.SubElement(channel, "description").text = "UK active tenders valued GBP 1,000 to 25,000"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    for notice in notices:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = notice["title"]
        ET.SubElement(item, "link").text = notice["url"]
        ET.SubElement(item, "guid", isPermaLink="false").text = notice["id"] + "-find-tender-v3"
        ET.SubElement(item, "pubDate").text = format_datetime(notice["published"])
        ET.SubElement(item, "description").text = (
            f'Advertised value: GBP {notice["amount"]:,.0f}\n'
            f'Status: active\nDeadline: {notice["deadline"]}\n\n'
            f'{notice["description"]}'
        )
    ET.ElementTree(rss).write(OUTPUT, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    results = fetch_notices()
    generate_feed(results)
    print(f"Generated Find a Tender RSS with {len(results)} notices")
