# -*- coding: utf-8 -*-
"""
RotoWire World Cup Lineups Scraper - Patch v1.2 surumu.

Dokuman Bolum 4'teki 5 duzeltme uygulanmistir:
  1. Her taraf ilk 11 BENZERSIZ isimle sinirlanir (trim) - secici XI altindaki
     sakatlar listesini de yakaliyor, trim olmadan sakat yedekler XI sanilir.
  2. SUS/OUT/QUES/GTD statuleri hem renk class'indan hem duz metinden yakalanir.
  3. Oyuncu adi a.title (tam isim) onceligiyle alinir - kisaltilmis isim yerine
     tam isim eslestirme oranini yukseltir.
  4. match_time alani tarihe parse edilir (bilgi amacli; eslestirme takim
     koduyla yapilir).
  5. Cron zamanlamasi workflow'da: 06:00 / 10:00 / 14:00 UTC.

NOT: Bu script TR'den CALISMAZ (ISP/BTK engeli). Yalnizca GitHub Actions
(ABD IP) uzerinden calistirilir. Lokal ortam sadece repo JSON'unu tuketir.
"""
import requests
from bs4 import BeautifulSoup
import json
import csv
import os
import re
from datetime import datetime, timezone

# -- Sabitler ------------------------------------------------
URL = "https://www.rotowire.com/soccer/lineups.php?league=WOC"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
DATA_DIR = "data"

# Statu etiketleri (duzeltme 2): hem class hem metinden yakalanir.
STATUS_TEXT_TAGS = ("OUT", "SUS", "QUES", "GTD")


def _status_from_class(pos_class):
    """Renk class'indan statu cikar (eski yontem)."""
    if "red" in pos_class:
        return "OUT"
    if "orange" in pos_class:
        return "GTD"
    if "yellow" in pos_class:
        return "QUES"
    return None


def _status_from_text(player_el):
    """Duzeltme 2: SUS bazi durumlarda class yerine duz metin etiketi olarak
    geliyor. Oyuncu satirinin tum metninde OUT/SUS/QUES/GTD tag'i ara."""
    txt = player_el.get_text(" ", strip=True).upper()
    for tag in STATUS_TEXT_TAGS:
        # Kelime siniri ile ara: "SUS" etiketi isim icine gomulu olmasin
        if re.search(r"\b" + tag + r"\b", txt):
            return tag
    return None


def parse_players(lineup_div, side):
    lst = lineup_div.select_one(f".lineup__list.{side}")
    if not lst:
        return []
    players = []
    seen_names = set()
    for p in lst.select(".lineup__player"):
        pos_el = p.select_one(".lineup__pos")
        a = p.select_one("a")
        if not a:
            continue
        href = a.get("href", "")
        player_id = href.rstrip("/").split("-")[-1]

        # Duzeltme 3: tam isim oncelikli (a.title), yoksa gorunen metin.
        name = a.get("title") or a.get_text(strip=True)
        if not name:
            continue

        # Duzeltme 1: ilk 11 BENZERSIZ isim. XI altindaki sakatlar listesi
        # ayni seciciye takiliyor; 11 dolunca veya isim tekrarinda kes.
        key = name.strip().lower()
        if key in seen_names:
            continue
        if len(players) >= 11:
            break
        seen_names.add(key)

        # Duzeltme 2: statu hem class'tan hem metinden.
        pos_class = pos_el.get("class", []) if pos_el else []
        status = _status_from_class(pos_class) or _status_from_text(p)

        players.append({
            "pos":         pos_el.get_text(strip=True) if pos_el else None,
            "name":        name,
            "player_id":   player_id,
            "status":      status,
            "profile_url": f"https://www.rotowire.com{href}",
        })
    return players


def parse_match_date(match_time_str, ref_year):
    """Duzeltme 4: 'June 12 3:00 PM ET' benzeri stringi ISO tarihe parse et.
    Eslestirme takim koduyla yapilir; bu alan yalnizca denetim icindir."""
    if not match_time_str:
        return None
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})", match_time_str)
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {ref_year}", "%B %d %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_lineups():
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    now_utc = datetime.now(timezone.utc)
    fetched_at = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = []

    for lineup in soup.select(".lineup.is-soccer"):
        time_el = lineup.select_one(".lineup__time")
        abbrs = [el.get_text(strip=True) for el in lineup.select(".lineup__abbr")]
        weather_el = lineup.select_one(".lineup__weather-text")
        statuses = [el.get_text(strip=True) for el in lineup.select(".lineup__status")]

        odds = {}
        for item in lineup.select(".lineup__odds-item"):
            label = item.select_one(".composite")
            if label:
                raw = label.get_text(" ", strip=True)
                odds[raw.split()[0]] = raw

        match_time = time_el.get_text(strip=True) if time_el else None

        matches.append({
            "fetched_at":   fetched_at,
            "match_time":   match_time,
            "match_date":   parse_match_date(match_time, now_utc.year),  # duzeltme 4
            "home_team":    abbrs[0] if len(abbrs) > 0 else None,
            "away_team":    abbrs[1] if len(abbrs) > 1 else None,
            "home_status":  statuses[0] if len(statuses) > 0 else None,
            "away_status":  statuses[1] if len(statuses) > 1 else None,
            "weather":      weather_el.get_text(" ", strip=True) if weather_el else None,
            "odds":         odds,
            "home_players": parse_players(lineup, "is-home"),
            "away_players": parse_players(lineup, "is-visit"),
        })

    return matches


def save_json(matches, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)
    print(f"  JSON kaydedildi -> {path}")


def save_csv(matches, path):
    fieldnames = [
        "fetched_at", "match_time", "match_date",
        "home_team", "away_team",
        "home_status", "away_status",
        "team", "side",
        "pos", "name", "player_id", "status", "profile_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in matches:
            base = {
                "fetched_at":  m["fetched_at"],
                "match_time":  m["match_time"],
                "match_date":  m["match_date"],
                "home_team":   m["home_team"],
                "away_team":   m["away_team"],
                "home_status": m["home_status"],
                "away_status": m["away_status"],
            }
            for p in m["home_players"]:
                writer.writerow({**base, "team": m["home_team"], "side": "home", **p})
            for p in m["away_players"]:
                writer.writerow({**base, "team": m["away_team"], "side": "away", **p})
    print(f"  CSV kaydedildi  -> {path}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Veri cekiliyor... ({today})")
    matches = fetch_lineups()
    total_players = sum(len(m["home_players"]) + len(m["away_players"]) for m in matches)
    print(f"   {len(matches)} mac, {total_players} oyuncu bulundu.")

    save_json(matches, os.path.join(DATA_DIR, f"lineups_{today}.json"))
    save_csv(matches, os.path.join(DATA_DIR, f"lineups_{today}.csv"))

    # Sabit isimli "en guncel" dosyalar - CRON-8 bunlari tuketir.
    save_json(matches, os.path.join(DATA_DIR, "lineups_latest.json"))
    save_csv(matches, os.path.join(DATA_DIR, "lineups_latest.csv"))

    print("Tamamlandi.")


if __name__ == "__main__":
    main()
