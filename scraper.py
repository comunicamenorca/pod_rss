#!/usr/bin/env python3
"""
Podcast RSS Generator
Genera feeds RSS de podcast a partir de pàgines web amb MP3s.
"""

import yaml
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import os
import sys
import re
import argparse
from urllib.parse import urljoin, urlparse
import time
import xml.etree.ElementTree as ET
from email.utils import format_datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


SPAIN_TZ = ZoneInfo("Europe/Madrid")
IB3_SCHEDULE_HOURS = {9, 10, 15, 16}


def is_scheduled_hour():
    now_spain = datetime.now(SPAIN_TZ)
    current_hour = now_spain.hour
    if current_hour in IB3_SCHEDULE_HOURS:
        print(f"⏰ Hora espanyola: {now_spain.strftime('%H:%M')} — execució programada ✅")
        return True
    else:
        print(f"⏰ Hora espanyola: {now_spain.strftime('%H:%M')} — fora d'horari, s'atura.")
        return False


def load_config(config_path="feeds.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_ib3_info(tag):
    """Extreu títol i data específicament per a pàgines IB3."""
    parent = tag.parent
    for _ in range(4):
        if parent is None:
            break
        text = parent.get_text(separator=" ", strip=True)
        if text:
            # Elimina la durada (ex: "15 min", "11 min")
            text = re.sub(r'\d+\s*min', '', text).strip()

            # Extreu la data i hora (ex: "29/05/2026 14:30:00")
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', text)
            date = None
            date_str = ""
            if date_match:
                date_str = date_match.group(1)
                try:
                    date = datetime.strptime(
                        f"{date_match.group(1)} {date_match.group(2)}",
                        "%d/%m/%Y %H:%M"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
                # Elimina la data del text per quedar-nos amb el títol net
                text = re.sub(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(:\d{2})?', '', text).strip()

            # El títol és el text restant si és prou llarg
            if len(text) > 5:
                title = f"{text} · {date_str}" if date_str else text
                return title, date

        parent = parent.parent
    return None, None


def get_mp3_links(url, session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ca,es;q=0.9,en;q=0.8",
    }
    response = session.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Detecta si és una pàgina IB3
    is_ib3 = "ib3" in url.lower() or "totib3" in url.lower()

    mp3s = []
    for tag in soup.find_all(["a", "source", "audio"]):
        href = tag.get("href") or tag.get("src") or ""
        if ".mp3" in href.lower():
            full_url = urljoin(url, href)

            if is_ib3:
                title, date = extract_ib3_info(tag)
            else:
                title, date = None, None

            if not title:
                title = extract_title(tag)
            if not date:
                date = extract_date(tag)

            mp3s.append({"url": full_url, "title": title, "date": date})

    # Elimina duplicats
    seen = set()
    unique = []
    for item in mp3s:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


def extract_title(tag):
    parent = tag.parent
    for _ in range(5):
        if parent is None:
            break
        for selector in ["h1", "h2", "h3", "h4", "strong", "span", "p", "li"]:
            el = parent.find(selector)
            if el:
                text = el.get_text(strip=True)
                if 3 < len(text) < 200:
                    return text
        parent = parent.parent

    if tag.name == "a" and tag.get_text(strip=True):
        return tag.get_text(strip=True)

    path = urlparse(tag.get("href") or tag.get("src") or "").path
    filename = os.path.basename(path).replace(".mp3", "").replace("-", " ").replace("_", " ")
    return filename or "Episodi sense títol"


def extract_date(tag):
    date_patterns = [
        (r"\d{2}/\d{2}/\d{4}", "%d/%m/%Y"),
        (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d"),
        (r"\d{2}\.\d{2}\.\d{4}", "%d.%m.%Y"),
    ]
    parent = tag.parent
    for _ in range(6):
        if parent is None:
            break
        text = parent.get_text()
        for pattern, fmt in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return datetime.strptime(match.group(), fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        parent = parent.parent
    return datetime.now(timezone.utc)


def generate_feed(feed_config, mp3_items, output_dir="docs"):
    os.makedirs(output_dir, exist_ok=True)

    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = feed_config["name"]
    ET.SubElement(channel, "link").text = feed_config["url"]
    ET.SubElement(channel, "description").text = feed_config.get("description", feed_config["name"])
    ET.SubElement(channel, "language").text = feed_config.get("language", "ca")
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    if feed_config.get("image"):
        img = ET.SubElement(channel, "image")
        ET.SubElement(img, "url").text = feed_config["image"]
        ET.SubElement(img, "title").text = feed_config["name"]
        ET.SubElement(img, "link").text = feed_config["url"]

    max_ep = feed_config.get("max_episodes", 50)
    for i, ep in enumerate(mp3_items[:max_ep]):
        title = ep["title"] or f"Episodi {i+1}"
        pub_date = ep["date"] or datetime.now(timezone.utc)

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = title
        ET.SubElement(item, "pubDate").text = format_datetime(pub_date)
        ET.SubElement(item, "guid").text = ep["url"]
        enc = ET.SubElement(item, "enclosure")
        enc.set("url", ep["url"])
        enc.set("type", "audio/mpeg")
        enc.set("length", "0")

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")

    filename = feed_config.get("output", feed_config["name"].lower().replace(" ", "-") + ".xml")
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="unicode", xml_declaration=False)

    print(f"✅ Feed generat: {filepath} ({len(mp3_items[:max_ep])} episodis)")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Genera feeds RSS de podcast")
    parser.add_argument("--config", default="feeds.yaml")
    parser.add_argument("--feed", default=None)
    parser.add_argument("--output", default="docs")
    parser.add_argument("--check-schedule", action="store_true")
    args = parser.parse_args()

    if args.check_schedule and not is_scheduled_hour():
        sys.exit(0)

    config = load_config(args.config)
    session = requests.Session()

    feeds = config.get("feeds", [])
    if args.feed:
        feeds = [f for f in feeds if f["name"] == args.feed]
        if not feeds:
            print(f"❌ Feed '{args.feed}' no trobat")
            sys.exit(1)

    for feed_config in feeds:
        print(f"\n🔍 Processant: {feed_config['name']}")
        print(f"   URL: {feed_config['url']}")
        try:
            mp3s = get_mp3_links(feed_config["url"], session)
            print(f"   Trobats {len(mp3s)} MP3s")
            if mp3s:
                print("   Títols extrets:")
                for ep in mp3s[:3]:
                    print(f"     · {ep['title']}")
            if not mp3s:
                print("   ⚠️  Cap MP3 trobat.")
                continue
            generate_feed(feed_config, mp3s, args.output)
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            continue
        time.sleep(1)


if __name__ == "__main__":
    main()
