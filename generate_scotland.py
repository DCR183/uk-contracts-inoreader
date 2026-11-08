
import json
import certifi
import ssl
import truststore
truststore.inject_into_ssl()
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

API = "https://api.publiccontractsscotland.gov.uk/v1/Notices"
MIN_VALUE = 1000
MAX_VALUE = 25000
OUTPUT = "scotland.xml"

def get_notices(month, notice_type):
    url = (
        f"{API}?dateFrom={month}&noticeType={notice_type}"
        "&outputType=0"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "UKTenderAlerts/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
        data = json.load(response)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("releases", data.get("records", []))
    return []

def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None

def main():
    now = datetime.now(timezone.utc)
    months = {
        now.strftime("%m-%Y"),
        (now.replace(day=1) -
         __import__("datetime").timedelta(days=1)).strftime("%m-%Y")
    }

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = (
        "Scotland Contract Opportunities"
    )
    ET.SubElement(channel, "link").text = (
        "https://www.publiccontractsscotland.gov.uk/"
    )
    ET.SubElement(channel, "description").text = (
        "Scottish public tenders valued GBP 1,000 to 25,000"
    )

    seen = set()
    count = 0

    for month in sorted(months):
        for notice_type in (2, 5, 102):
            try:
                releases = get_notices(month, notice_type)
            except Exception as error:
                print(f"API error {month}/{notice_type}: {error}")
                continue

            for release in releases:
                if not isinstance(release, dict):
                    continue

                tender = release.get("tender") or {}
                if not isinstance(tender, dict):
                    continue

                if tender.get("status") != "active":
                    continue

                value = tender.get("value") or {}
                if not isinstance(value, dict):
                    continue

                if value.get("currency") != "GBP":
                    continue

                try:
                    amount = float(value["amount"])
                except (KeyError, ValueError, TypeError):
                    continue

                if not MIN_VALUE <= amount <= MAX_VALUE:
                    continue

                period = tender.get("tenderPeriod") or {}
                deadline = parse_date(period.get("endDate"))
                if not deadline or deadline <= now:
                    continue

                ocid = release.get("ocid", "")
                notice_id = release.get("id", ocid)
                if not notice_id or notice_id in seen:
                    continue

                seen.add(notice_id)

                title = tender.get("title") or "Scottish tender"
                description = tender.get("description") or ""
                published = parse_date(release.get("date")) or now

                documents = tender.get("documents") or []
                links = [
                    doc.get("url")
                    for doc in documents
                    if isinstance(doc, dict) and doc.get("url")
                ]

                link = next(
                    (
                        url for url in links
                        if "publiccontractsscotland.gov.uk" in url
                    ),
                    None
                )

                if not link:
                    link = (
                        "https://www.publiccontractsscotland.gov.uk/"
                        "search/search_switch.aspx"
                    )

                item = ET.SubElement(channel, "item")
                ET.SubElement(item, "title").text = title
                ET.SubElement(item, "link").text = link
                ET.SubElement(
                    item, "guid", isPermaLink="false"
                ).text = f"scotland-{notice_id}"
                ET.SubElement(item, "pubDate").text = (
                    format_datetime(published)
                )
                ET.SubElement(item, "description").text = (
                    f"Status: active\n"
                    f"Value: GBP {amount:,.2f}\n"
                    f"Deadline: {deadline.isoformat()}\n"
                    f"Reference: {ocid}\n\n{description}"
                )
                count += 1

    ET.ElementTree(rss).write(
        OUTPUT, encoding="utf-8", xml_declaration=True
    )
    print(f"Created {OUTPUT} with {count} opportunities")

if __name__ == "__main__":
    main()
