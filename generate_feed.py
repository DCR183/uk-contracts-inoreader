
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

API = (
    "https://www.contractsfinder.service.gov.uk/"
    "Published/Notices/OCDS/Search?limit=100"
)
OUTPUT = "feed.xml"

def fetch():
    request = urllib.request.Request(
        API, headers={"User-Agent": "UKContractsRSS/1.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)

def collect_notices(data):
    results = []
    for release in data.get("releases", []):
        tender = release.get("tender") or {}
        value = tender.get("value") or {}
        amount = value.get("amount")
        if amount is None:
            continue
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            continue
        if not 1000 <= amount <= 25000:
            continue
        if value.get("currency", "GBP") != "GBP":
            continue
        title = tender.get("title") or "Untitled contract"
        description = tender.get("description") or ""
        identifier = release.get("ocid") or release.get("id")
        if not identifier:
            continue
        url = (
            "https://www.contractsfinder.service.gov.uk/"
            "Search?searchTerm=" +
            urllib.parse.quote(title)
        )
        results.append({
            "title": title,
            "description": description,
            "amount": amount,
            "id": identifier,
            "url": url,
            "date": release.get("date")
        })
    return results

def build_feed(notices):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "UK Contracts Finder Opportunities"
    ET.SubElement(channel, "link").text = (
        "https://www.contractsfinder.service.gov.uk/"
    )
    ET.SubElement(channel, "description").text = (
        "UK procurement opportunities valued £1,000–£25,000"
    )
    for notice in notices:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = notice["title"]
        ET.SubElement(item, "link").text = notice["url"]
        ET.SubElement(item, "guid", isPermaLink="false").text = notice["id"]
        ET.SubElement(item, "description").text = (
            f'Advertised value: £{notice["amount"]:,.0f}\n'
            + notice["description"]
        )
        if notice["date"]:
            try:
                date = datetime.fromisoformat(
                    notice["date"].replace("Z", "+00:00")
                )
                ET.SubElement(item, "pubDate").text = format_datetime(date)
            except ValueError:
                pass
    ET.indent(rss)
    ET.ElementTree(rss).write(
        OUTPUT, encoding="utf-8", xml_declaration=True
    )

if __name__ == "__main__":
    import urllib.parse
    data = fetch()
    notices = collect_notices(data)
    build_feed(notices)
    print(f"Generated RSS with {len(notices)} notices")
