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
# IB3 publica a les ~9h i ~15h hora Menorca
# Comprovem a les 9h, 9:30h, 10h, 15h, 15:30h i 16h
IB3_SCHEDULE = {
    9:  "mati",
    15: "tarda",
}
IB3_RETRY_HOURS = {
    10: "mati",   # reintent si a les 9h i 9:30h no hi havia res
    16: "tarda",  # reintent si a les 15h i 15:30h no hi havia res
}
IB3_RETRY_MINUTES = {30}  # minuts dins l'hora on fem reintent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ca,es;q=0.9,en;q=0.8",
}


def is_scheduled_hour(output_dir="docs", feed_config=None):
    import os
    now_spain = datetime.now(SPAIN_TZ)
    current_hour = now_spain.hour
    current_minute = now_spain.minute

    def ja_hi_ha_episodi_avui(franja_hores):
        """Comprova si el feed ja s'ha actualitzat avui durant alguna de les hores indicades."""
        if not feed_config:
            return False
        filename = feed_config.get("output", "feed.xml")
        filepath = os.path.join(output_dir, filename)
        if os.path.exists(filepath):
            last_mod_dt = datetime.fromtimestamp(os.path.getmtime(filepath), tz=SPAIN_TZ)
            return last_mod_dt.date() == now_spain.date() and last_mod_dt.hour in franja_hores
        return False

    # Hores principals: sempre executar
    if current_hour in IB3_SCHEDULE:
        print(f"⏰ {now_spain.strftime('%H:%M')} — hora principal ✅")
        return True

    # Reintent a les X:30 (9:30h o 15:30h)
    retry_base = current_hour if current_minute in IB3_RETRY_MINUTES else None
    if retry_base in IB3_SCHEDULE:
        franja_nom = "matí" if IB3_SCHEDULE[retry_base] == "mati" else "tarda"
        if ja_hi_ha_episodi_avui({retry_base}):
            print(f"⏰ {now_spain.strftime('%H:%M')} — ja hi havia episodi de {franja_nom}, s'atura.")
            return False
        print(f"⏰ {now_spain.strftime('%H:%M')} — reintent :30 {franja_nom} ✅")
        return True

    # Reintent a les 10h i 16h: executar si no hi ha hagut episodi a la franja anterior
    if current_hour in IB3_RETRY_HOURS:
        franja = IB3_RETRY_HOURS[current_hour]
        franja_nom = "matí" if franja == "mati" else "tarda"
        hores_anteriors = {current_hour - 1, current_hour - 1}  # 9h per 10h, 15h per 16h
        if ja_hi_ha_episodi_avui(hores_anteriors):
            print(f"⏰ {now_spain.strftime('%H:%M')} — ja hi havia episodi de {franja_nom}, s'atura.")
            return False
        print(f"⏰ {now_spain.strftime('%H:%M')} — reintent hora completa {franja_nom} ✅")
        return True

    print(f"⏰ {now_spain.strftime('%H:%M')} — fora d'horari, s'atura.")
    return False


def load_config(config_path="feeds.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_radioestel_episodes(soup, base_url):
    """
    Extreu episodis de Ràdio Estel.
    Estructura:
      <p class="... font-bold text-gray-800">21 maig 2026</p>
      <p class="... text-gray-500">Títol de l'episodi</p>
      <article class="... episode-content-article ...">Descripció...</article>
      <source src="https://...mp3">
    """
    episodes = []

    # Troba tots els contenidors d'episodi (audio-player-container)
    containers = soup.find_all("div", class_=lambda c: c and "audio-player-container" in c)

    for container in containers:
        # MP3
        source = container.find("source")
        if not source or not source.get("src", "").endswith(".mp3"):
            # Busca també <a> amb .mp3
            a = container.find("a", href=lambda h: h and ".mp3" in h)
            mp3_url = urljoin(base_url, a["href"]) if a else None
        else:
            mp3_url = source["src"]

        if not mp3_url:
            continue

        # Data: p amb font-bold text-gray-800
        date_el = container.find("p", class_=lambda c: c and "font-bold" in c and "text-gray-800" in c)
        date_text = date_el.get_text(strip=True) if date_el else ""
        date = parse_catalan_date(date_text)

        # Títol: p amb text-gray-500
        title_el = container.find("p", class_=lambda c: c and "text-gray-500" in c)
        title = title_el.get_text(strip=True) if title_el else date_text

        # Descripció: article amb episode-content-article
        desc_el = container.find("article", class_=lambda c: c and "episode-content-article" in c)
        description = desc_el.get_text(separator=" ", strip=True) if desc_el else title

        episodes.append({
            "url": mp3_url,
            "title": title,
            "date": date,
            "description": description,
        })

    return episodes


def parse_catalan_date(text):
    """Converteix dates en català com '21 maig 2026' a datetime."""
    months = {
        "gener": 1, "febrer": 2, "març": 3, "abril": 4,
        "maig": 5, "juny": 6, "juliol": 7, "agost": 8,
        "setembre": 9, "octubre": 10, "novembre": 11, "desembre": 12
    }
    text = text.lower().strip()
    match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', text)
    if match:
        day, month_name, year = match.groups()
        month = months.get(month_name)
        if month:
            try:
                return datetime(int(year), month, int(day), tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


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


def get_mp3_links(url, session):
    response = session.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    is_ib3 = "ib3" in url.lower() or "totib3" in url.lower()
    is_radioestel = "radioestel" in url.lower()

    # Ràdio Estel: parser específic
    if is_radioestel:
        episodes = extract_radioestel_episodes(soup, url)
        if episodes:
            return episodes
        # Fallback genèric si no troba res
        print("   ⚠️  Parser Ràdio Estel no ha trobat episodis, usant parser genèric")

    mp3s = []
    seen = set()

    for tag in soup.find_all(["a", "source", "audio"]):
        href = tag.get("href") or tag.get("src") or ""
        if ".mp3" not in href.lower():
            continue

        mp3_url = urljoin(url, href)
        if mp3_url in seen:
            continue
        seen.add(mp3_url)

        if is_ib3:
            title, date = extract_ib3_info(tag)
            description = None
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

    config = load_config(args.config)

    if args.check_schedule:
        feeds_list = config.get("feeds", [])
        feed_for_schedule = next((f for f in feeds_list if f["name"] == args.feed), feeds_list[0] if feeds_list else None) if args.feed else feeds_list[0] if feeds_list else None
        if not is_scheduled_hour(args.output, feed_for_schedule):
            sys.exit(0)
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
            print(f"   Trobats {len(mp3s)} episodis")
            if mp3s:
                print("   Primers episodis:")
                for ep in mp3s[:3]:
                    print(f"     · {ep['title']}")
                    if ep.get('description'):
                        print(f"       {ep['description'][:100]}...")
            if not mp3s:
                print("   ⚠️  Cap episodi trobat.")
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
