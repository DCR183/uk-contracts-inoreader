
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

API = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
OUTPUT = "find_tender.xml"
MIN_VALUE = 1000
MAX_VALUE = 25000
MAX_PAGES = 10


def fetch_notices():
    notices = {}
    cursor = None

    for page in range(MAX_PAGES):
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        url = API + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "UKTenderRSS/1.0"}
        )

        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)

        packages = data.get("releases", [])
        if not packages:
            break

        for release in packages:
            tender = release.get("tender") or {}
            status = tender.get("status", "").lower()

            if status != "active":
                continue

            value = tender.get("value") or {}
            amount = value.get("amount")
            currency = value.get("currency", "GBP")

            if amount is None or currency != "GBP":
                continue

            amount = float(amount)
            if not MIN_VALUE <= amount <= MAX_VALUE:
                continue

            deadline = tender.get("tenderPeriod", {}).get("endDate")
            if not deadline:
                continue

            try:
                closing = datetime.fromisoformat(
                    deadline.replace("Z", "+00:00")
                )
                if closing <= datetime.now(timezone.utc):
                    continue
            except ValueError:
                continue

            title = tender.get("title") or "Untitled tender"
            identifier = release.get("ocid") or release.get("id")
            if not identifier:
                continue

            description = tender.get("description") or ""
            notice_url = (
                "https://www.find-tender.service.gov.uk/"
                "Search/Results?keywords="
                + urllib.parse.quote(title)
            )

            notices[identifier] = {
                "title": title,
                "description": description,
                "amount": amount,
                "deadline": deadline,
                "url": notice_url,
                "id": identifier,
            }

        cursor = data.get("nextCursor")
        if not cursor:
            break

    return list(notices.values())


def generate_feed(notices):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = (
        "UK Find a Tender Opportunities"
    )
    ET.SubElement(channel, "link").text = (
        "https://www.find-tender.service.gov.uk/"
    )
    ET.SubElement(channel, "description").text = (
        "UK active tenders valued GBP 1,000 to 25,000"
    )

    for notice in notices:
        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = notice["title"]
        ET.SubElement(item, "link").text = notice["url"]

        ET.SubElement(
            item, "guid", isPermaLink="false"
        ).text = notice["id"] + "-find-tender-v1"

        details = (
            f'Advertised value: GBP {notice["amount"]:,.0f}\n'
            f'Status: active\n'
            f'Deadline: {notice["deadline"]}\n\n'
            f'{notice["description"]}'
        )

        ET.SubElement(item, "description").text = details

    ET.ElementTree(rss).write(
        OUTPUT,
        encoding="utf-8",
        xml_declaration=True
    )


if __name__ == "__main__":
    results = fetch_notices()
    generate_feed(results)
    print(f"Generated Find a Tender RSS with {len(results)} notices")
