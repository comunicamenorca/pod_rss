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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca,es;q=0.9,en;q=0.8",
}


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


def fetch_episode_detail(episode_url, session):
    """Entra a la pàgina individual d'un episodi i n'extreu títol i descripció."""
    try:
        response = session.get(episode_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Títol: cerca og:title, llavors h1, llavors title
        title = None
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "").strip()
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True).split("|")[0].strip()

        # Descripció: cerca og:description, llavors el primer <p> llarg
        description = None
        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            description = og_desc.get("content", "").strip()
        if not description:
            for p in soup.find_all("p"):
                txt = p.get_text(strip=True)
                if len(txt) > 50:
                    description = txt
                    break

        return title, description
    except Exception as e:
        print(f"     ⚠️  No s'ha pogut carregar {episode_url}: {e}")
        return None, None


def extract_ib3_info(tag):
    """Extreu títol i data específicament per a pàgines IB3."""
    parent = tag.parent
    for _ in range(4):
        if parent is None:
            break
        text = parent.get_text(separator=" ", strip=True)
        if text:
            text = re.sub(r'\d+\s*min', '', text).strip()
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
                text = re.sub(r'\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(:\d{2})?', '', text).strip()
            if len(text) > 5:
                title = f"{text} · {date_str}" if date_str else text
                return title, date
        parent = parent.parent
    return None, None


def get_episode_links(url, session):
    """Extreu els enllaços a pàgines individuals d'episodis (per webs WordPress)."""
    response = session.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    episode_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Enllaços interns que semblin episodis (contenen la URL base)
        if href.startswith(url) or (href.startswith("/") and url in href):
            full = urljoin(url, href)
            if full != url and full not in episode_links:
                episode_links.append(full)

    return episode_links


def get_mp3_links(url, session, fetch_details=False):
    """Extreu tots els MP3 d'una pàgina, opcionalment entrant a cada episodi."""
    response = session.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    is_ib3 = "ib3" in url.lower() or "totib3" in url.lower()

    # Recull tots els MP3 amb el seu context
    mp3_tags = []
    for tag in soup.find_all(["a", "source", "audio"]):
        href = tag.get("href") or tag.get("src") or ""
        if ".mp3" in href.lower():
            mp3_tags.append((tag, urljoin(url, href)))

    # Si és WordPress i volem detalls, cerca els enllaços d'episodis a prop dels MP3
    episode_page_map = {}
    if fetch_details and not is_ib3:
        for tag, mp3_url in mp3_tags:
            # Cerca un <a> proper que apunti a una pàgina d'episodi
            parent = tag.parent
            for _ in range(6):
                if parent is None:
                    break
                for a in parent.find_all("a", href=True):
                    href = a["href"]
                    # Ha de ser una URL de la mateixa web, no un MP3
                    if (url.split("/")[2] in href or href.startswith("/")) and ".mp3" not in href:
                        ep_url = urljoin(url, href)
                        if ep_url != url:
                            episode_page_map[mp3_url] = ep_url
                            break
                if mp3_url in episode_page_map:
                    break
                parent = parent.parent

    mp3s = []
    seen = set()

    for tag, mp3_url in mp3_tags:
        if mp3_url in seen:
            continue
        seen.add(mp3_url)

        if is_ib3:
            title, date = extract_ib3_info(tag)
            description = None
        elif fetch_details and mp3_url in episode_page_map:
            ep_url = episode_page_map[mp3_url]
            print(f"     → Carregant episodi: {ep_url}")
            title, description = fetch_episode_detail(ep_url, session)
            date = extract_date(tag)
            time.sleep(0.5)
        else:
            title = extract_title(tag)
            description = None
            date = extract_date(tag)

        if not title:
            title = extract_title(tag)
        if not date:
            date = extract_date(tag)

        mp3s.append({"url": mp3_url, "title": title, "date": date, "description": description})

    return mp3s


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
        itunes_img = ET.SubElement(channel, "itunes:image")
        itunes_img.set("href", feed_config["image"])

    max_ep = feed_config.get("max_episodes", 50)
    for i, ep in enumerate(mp3_items[:max_ep]):
        title = ep["title"] or f"Episodi {i+1}"
        pub_date = ep["date"] or datetime.now(timezone.utc)
        description = ep.get("description") or title

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = description
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
            fetch_details = feed_config.get("fetch_episode_details", False)
            mp3s = get_mp3_links(feed_config["url"], session, fetch_details=fetch_details)
            print(f"   Trobats {len(mp3s)} MP3s")
            if mp3s:
                print("   Primers episodis:")
                for ep in mp3s[:3]:
                    print(f"     · {ep['title']}")
                    if ep.get('description'):
                        print(f"       {ep['description'][:80]}...")
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
