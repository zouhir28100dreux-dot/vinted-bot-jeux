import requests
import json
import os
import sys
import time
from pathlib import Path

# ---------- CONFIG ----------
VINTED_DOMAIN = os.environ.get("VINTED_DOMAIN", "vinted.fr")
SEARCH_TEXT = os.environ.get("VINTED_SEARCH", "jeux video")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
SEEN_FILE = Path("seen_items.json")
MAX_SEEN_KEPT = 800

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def get_session() -> requests.Session:
    """Crée une session et va chercher les cookies anti-bot en visitant la page d'accueil."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f"https://www.{VINTED_DOMAIN}/", timeout=15)
    return s


def fetch_items(session: requests.Session, search_text: str, per_page: int = 20):
    url = f"https://www.{VINTED_DOMAIN}/api/v2/catalog/items"
    params = {
        "search_text": search_text,
        "order": "newest_first",
        "per_page": per_page,
    }
    r = session.get(url, params=params, timeout=15)
    if r.status_code in (401, 403):
        return None
    r.raise_for_status()
    return r.json().get("items", [])


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except json.JSONDecodeError:
            return set()
    return set()


def save_seen(seen: set):
    trimmed = list(seen)[-MAX_SEEN_KEPT:]
    SEEN_FILE.write_text(json.dumps(trimmed))


def notify_discord(item: dict):
    price = item.get("price", {})
    photo = item.get("photo") or {}
    embed = {
        "title": item.get("title", "Nouvelle annonce")[:256],
        "url": f"https://www.{VINTED_DOMAIN}/items/{item['id']}",
        "description": f"💶 {price.get('amount', '?')} {price.get('currency_code', '')}\n"
                        f"👤 {item.get('user', {}).get('login', 'inconnu')}",
        "color": 5793266,
    }
    if photo.get("url"):
        embed["image"] = {"url": photo["url"]}

    payload = {"embeds": [embed]}
    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)
    if resp.status_code == 429:
        # rate limit Discord, on attend et on retente une fois
        retry_after = resp.json().get("retry_after", 1)
        time.sleep(retry_after + 0.5)
        requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)


def main():
    if not DISCORD_WEBHOOK:
        print("ERREUR: la variable DISCORD_WEBHOOK_URL n'est pas définie.")
        sys.exit(1)

    session = get_session()
    items = fetch_items(session, SEARCH_TEXT)

    if items is None:
        print("Bloqué (401/403), nouvelle tentative avec une session fraîche...")
        time.sleep(3)
        session = get_session()
        items = fetch_items(session, SEARCH_TEXT)
        if items is None:
            print("Toujours bloqué, on arrête ce passage (on retentera au prochain run).")
            sys.exit(0)

    seen = load_seen()
    new_items = [it for it in items if str(it["id"]) not in seen]

    # On envoie du plus ancien au plus récent pour un ordre logique dans Discord
    for it in reversed(new_items):
        try:
            notify_discord(it)
        except Exception as e:
            print(f"Erreur envoi Discord pour l'item {it.get('id')}: {e}")
        seen.add(str(it["id"]))

    save_seen(seen)
    print(f"{len(new_items)} nouvelle(s) annonce(s) envoyée(s) sur {len(items)} récupérée(s).")


if __name__ == "__main__":
    main()
