"""Import only Senna's manually maintained Product cards, without a Ghost API key."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from friend_circle_lite import HEADERS_JSON


def http_url(value: str, base_url: str = "", *, homepage: bool = False) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Missing URL")
    parts = urlsplit(urljoin(base_url, value))
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Expected an HTTP(S) URL without credentials")
    # Ghost adds ?ref=<site> to outbound links; it is not part of a friend's identity.
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                       if key != "ref"]) if homepage else parts.query
    path = (parts.path.rstrip("/") + "/") if homepage else parts.path
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))


def extract_friends(html: str, page_url: str) -> dict:
    page_url = http_url(page_url)
    soup = BeautifulSoup(html, "html.parser")
    directories = soup.select(".friends-page .friends-directory")
    if len(directories) != 1:
        raise ValueError("Expected exactly one Senna Friends directory")
    cards = directories[0].select(".kg-product-card")
    if not cards:
        raise ValueError("The Ghost directory is empty; refusing to replace the published list")
    friends, names, urls = [], set(), set()
    for index, card in enumerate(cards, start=1):
        title = card.select_one(".kg-product-card-title")
        button = card.select_one("a.kg-product-card-button[href]")
        avatar = card.select_one("img.kg-product-card-image[src]")
        name = " ".join(title.stripped_strings) if title else ""
        if not name or button is None:
            raise ValueError(f"Card {index} needs a name and an enabled Product button with a URL")
        url = http_url(button["href"], page_url, homepage=True)
        if name in names or url in urls:
            raise ValueError(f"Card {index} duplicates a name or homepage URL")
        names.add(name)
        urls.add(url)
        friends.append({"name": name, "url": url,
                        "avatar": http_url(avatar["src"], page_url) if avatar else ""})
    return {"friends": friends}


def sync_directory(page_url: str, output: Path) -> dict:
    page_url = http_url(page_url)
    response = requests.get(page_url, headers=HEADERS_JSON, timeout=(10, 30))
    response.raise_for_status()
    # Use the final URL to resolve relative image URLs after canonical redirects.
    payload = extract_friends(response.text, response.url)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(output)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return payload


def validate_feed(directory: dict, feed: dict) -> None:
    """Gate publication so a failed crawl cannot replace good data with an empty feed."""
    friends = {friend["name"]: friend for friend in directory["friends"]}
    articles = feed.get("article_data")
    stats = feed.get("statistical_data", {})
    if not friends or not isinstance(articles, list) or not articles:
        raise ValueError("No articles were collected; keeping the previous deployment")
    if stats.get("friends_num") != len(friends) or stats.get("article_num") != len(articles):
        raise ValueError("Feed counts do not match this run's Ghost directory/results")
    for article in articles:
        friend = friends.get(article.get("author"))
        if not friend or article.get("avatar", "") != friend["avatar"]:
            raise ValueError("Article metadata does not match the current Ghost directory")
        if not article.get("title"):
            raise ValueError("Article has no title")
        http_url(article.get("link", ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("GHOST_FRIENDS_URL", ""))
    parser.add_argument("--output", type=Path, default=Path("temp/ghost-friends.json"))
    parser.add_argument("--validate-feed", type=Path)
    args = parser.parse_args()
    try:
        if args.validate_feed:
            validate_feed(json.loads(args.output.read_text(encoding="utf-8")),
                          json.loads(args.validate_feed.read_text(encoding="utf-8")))
            print("Feed matches the Ghost directory; publication may proceed.")
        else:
            if not args.url:
                raise ValueError("Set the GHOST_FRIENDS_URL repository variable to the public Ghost Friends page")
            payload = sync_directory(args.url, args.output)
            print(f"Imported {len(payload['friends'])} Ghost Product cards into {args.output}")
    except (ValueError, OSError, requests.RequestException) as error:
        parser.exit(1, f"Ghost directory sync failed: {error}\n")


if __name__ == "__main__":
    main()
