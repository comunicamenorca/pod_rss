#!/usr/bin/env python3
"""
Podcast RSS Generator
Genera feeds RSS de podcast a partir de pàgines web amb MP3s.
"""

import yaml
import requests
from bs4 import BeautifulSoup
from rfeed import Feed, Item, Enclosure, Guid
from datetime import datetime, timezone
import os
import sys
import re
import argparse
from urllib.parse import urljoin, urlparse
from email.utils import formatdate
import time


def load_config(config_path="feeds.yaml"):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_mp3_links(url, session):
    """Extreu tots els enllaços MP3 d'una pàgina web."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ca,es;q=0.9,en;q=0.8",
    }
    response = session.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    mp3s = []

    # Busca enllaços directes a MP3
    for tag in soup.find_all(["a", "source", "audio"]):
        href = tag.get("href") or tag.get("src") or ""
        if href.lower().endswith(".mp3") or ".mp3" in href.lower():
            full_url = urljoin(url, href)
            # Busca el títol més proper
            title = extract_title(tag, soup)
            # Busca la data més propera
            date = extract_date(tag, soup)
            mp3s.append({
                "url": full_url,
                "title": title,
                "date": date,
            })

    # Elimina duplicats mantenint ordre
    seen = set()
    unique = []
    for item in mp3s:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    return unique


def extract_title(tag, soup):
    """Intenta extreure un títol proper a l'element."""
    # Puja l'arbre cercant text significatiu
    parent = tag.parent
    for _ in range(5):
        if parent is None:
            break
        # Busca encapçalaments, spans amb text
        for selector in ["h1", "h2", "h3", "h4", "strong", "span", "p", "li"]:
            el = parent.find(selector)
            if el and el.get_text(strip=True):
                text = el.get_text(strip=True)
                if len(text) > 3 and len(text) < 200:
                    return text
        parent = parent.parent

    # Si l'element és un <a>, usa el text
    if tag.name == "a" and tag.get_text(strip=True):
        return tag.get_text(strip=True)

    # Nom del fitxer com a fallback
    path = urlparse(tag.get("href") or tag.get("src") or "").path
    filename = os.path.basename(path).replace(".mp3", "").replace("-", " ").replace("_", " ")
    return filename or "Episodi sense títol"


def extract_date(tag, soup):
    """Intenta extreure una data propera a l'element."""
    date_patterns = [
        r"\d{2}/\d{2}/\d{4}",   # 29/05/2026
        r"\d{4}-\d{2}-\d{2}",   # 2026-05-29
        r"\d{2}\.\d{2}\.\d{4}", # 29.05.2026
    ]

    parent = tag.parent
    for _ in range(6):
        if parent is None:
            break
        text = parent.get_text()
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                date_str = match.group()
                try:
                    for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"]:
                        try:
                            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                        except ValueError:
                            continue
                except Exception:
                    pass
        parent = parent.parent

    return datetime.now(timezone.utc)


def generate_feed(feed_config, mp3_items, output_dir="docs"):
    """Genera el fitxer RSS a partir dels elements MP3 trobats."""
    os.makedirs(output_dir, exist_ok=True)

    items = []
    for i, ep in enumerate(mp3_items[:feed_config.get("max_episodes", 50)]):
        title = ep["title"] or f"Episodi {i+1}"
        pub_date = ep["date"] or datetime.now(timezone.utc)

        rss_item = Item(
            title=title,
            link=ep["url"],
            description=title,
            enclosure=Enclosure(
                url=ep["url"],
                type="audio/mpeg",
                length=0,
            ),
            pubDate=pub_date,
            guid=Guid(ep["url"]),
        )
        items.append(rss_item)

    feed = Feed(
        title=feed_config["name"],
        link=feed_config["url"],
        description=feed_config.get("description", feed_config["name"]),
        language=feed_config.get("language", "ca"),
        lastBuildDate=datetime.now(timezone.utc),
        items=items,
        image=feed_config.get("image", None),
    )

    filename = feed_config.get("output", feed_config["name"].lower().replace(" ", "-") + ".xml")
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(feed.rss())

    print(f"✅ Feed generat: {filepath} ({len(items)} episodis)")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Genera feeds RSS de podcast")
    parser.add_argument("--config", default="feeds.yaml", help="Fitxer de configuració")
    parser.add_argument("--feed", default=None, help="Nom del feed a processar (tots si no s'especifica)")
    parser.add_argument("--output", default="docs", help="Directori de sortida")
    args = parser.parse_args()

    config = load_config(args.config)
    session = requests.Session()

    feeds = config.get("feeds", [])
    if args.feed:
        feeds = [f for f in feeds if f["name"] == args.feed]
        if not feeds:
            print(f"❌ Feed '{args.feed}' no trobat al fitxer de configuració")
            sys.exit(1)

    for feed_config in feeds:
        print(f"\n🔍 Processant: {feed_config['name']}")
        print(f"   URL: {feed_config['url']}")
        try:
            mp3s = get_mp3_links(feed_config["url"], session)
            print(f"   Trobats {len(mp3s)} MP3s")
            if not mp3s:
                print("   ⚠️  Cap MP3 trobat. Comprova la URL o l'estructura de la pàgina.")
                continue
            generate_feed(feed_config, mp3s, args.output)
        except Exception as e:
            print(f"   ❌ Error: {e}")
            continue

        time.sleep(1)  # Respecta el servidor


if __name__ == "__main__":
    main()
