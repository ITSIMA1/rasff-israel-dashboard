"""
RASFF-Israel Dashboard Pipeline
================================
שולף התראות מ-RASFF, מצליב מול נתוני יבוא ישראל (מכס), ומייצר results.json לדשבורד.

הרצה: python pipeline.py
"""

import json
import sys
import time
from datetime import datetime

import httpx
import requests

# ── קבועים ─────────────────────────────────────────────────────────────────

RASFF_URL = "https://webgate.ec.europa.eu/rasff-window/backend/public/notification/search/consolidated/en/"
RASFF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer":    "https://webgate.ec.europa.eu/rasff-window/screen/search",
    "Content-Type": "application/json",
    "Accept":     "application/json, text/plain, */*",
    "Origin":     "https://webgate.ec.europa.eu",
}

CUSTOMS_API    = "https://data.gov.il/api/3/action/datastore_search"
CUSTOMS_RES_26 = "6b0a2694-889f-4908-94dc-4ead004d719a"
CUSTOMS_RES_25 = "8c2be932-d9c3-4d93-a748-ad45e76eddde"   # ייתכן שיש גם 2025

# מיפוי קטגוריה RASFF → פרקי HS דו-ספרתיים שרלוונטיים ליבוא לישראל
CATEGORY_TO_HS_CHAPTERS: dict[str, list[str]] = {
    "milk and milk products":                            ["04", "19"],
    "dietetic foods, food supplements and fortified foods": ["04", "19", "21"],
    "cereals and bakery products":                       ["10", "11", "19"],
    "meat and meat products (other than poultry)":       ["02", "16"],
    "poultry meat and poultry meat products":            ["02", "16"],
    "fish and fish products":                            ["03", "16"],
    "fruits and vegetables":                             ["07", "08"],
    "nuts, nut products and seeds":                      ["08", "12"],
    "herbs and spices":                                  ["09"],
    "confectionery":                                     ["17", "18"],
    "cocoa and cocoa preparations, coffee and tea":      ["09", "18"],
    "eggs and egg products":                             ["04"],
    "prepared dishes and snacks":                        ["16", "19", "21"],
    "soups, broths, sauces and condiments":              ["21"],
    "other food product / mixed":                        ["21"],
    "honey and royal jelly":                             ["04"],
    "bivalve molluscs and products thereof":             ["03"],
    "cephalopods and products thereof":                  ["03"],
    "crustaceans and products thereof":                  ["03"],
    "food contact materials":                            [],   # לא מוצר מזון — לדלג
    "food additives and flavourings":                    ["21"],
    "alcoholic beverages":                               ["22"],
    "non-alcoholic beverages":                           ["22"],
    "wine":                                              ["22"],
    "animal feed":                                       ["23"],
}

PAGES_TO_FETCH = 4          # 4 × 50 = 200 התראות (~2 שבועות)
CUSTOMS_LIMIT  = 500        # מקסימום רשומות לכל שאילתת מכס


# ── RASFF ───────────────────────────────────────────────────────────────────

def fetch_rasff_page(client: httpx.Client, page: int, per_page: int = 50) -> dict:
    body = {
        "parameters": {"pageNumber": page, "itemsPerPage": per_page},
        "notificationReference": None, "subject":          None,
        "notifyingCountry":      None, "originCountry":    None,
        "distributionCountry":   None, "notificationType": None,
        "notificationStatus":    None, "notificationClassification": None,
        "notificationBasis":     None, "productCategory":  None,
        "actionTaken":           None, "hazardCategory":   None,
        "riskDecision":          None,
    }
    r = client.post(RASFF_URL, json=body, headers=RASFF_HEADERS)
    r.raise_for_status()
    return r.json()


def fetch_rasff_recent(pages: int = PAGES_TO_FETCH) -> list[dict]:
    """שולף את ה-pages האחרונות של RASFF (ממוינות לפי תאריך — חדשות קודם)."""
    print(f"[RASFF] שולף {pages} עמודים × 50 = עד {pages * 50} התראות...")
    all_notifs: list[dict] = []
    with httpx.Client(verify=False, timeout=30) as client:
        for page in range(1, pages + 1):
            data = fetch_rasff_page(client, page)
            notifs = data.get("notifications", [])
            all_notifs.extend(notifs)
            total = data.get("totalElements", "?")
            print(f"  עמוד {page}: {len(notifs)} התראות (סה\"כ ב-RASFF: {total})")
            if len(notifs) < 50:
                break   # עמוד חלקי — הגענו לסוף
            time.sleep(0.5)
    print(f"[RASFF] סה\"כ נשלף: {len(all_notifs)} התראות")
    return all_notifs


# ── Customs ─────────────────────────────────────────────────────────────────

_customs_cache: dict[str, list[dict]] = {}


def fetch_customs(chapter: str, origin_iso: str | None = None) -> list[dict]:
    """
    שולף רשומות מכס לפרק HS נתון, אופציונלית ממוקדות למדינת מקור.
    cache_key = "chapter" או "chapter:ISO"
    """
    cache_key = f"{chapter}:{origin_iso}" if origin_iso else chapter
    if cache_key in _customs_cache:
        return _customs_cache[cache_key]

    filters: dict = {"CustomsItem_2_Digits": chapter}
    if origin_iso:
        filters["Origin_Country"] = origin_iso

    params = {
        "resource_id": CUSTOMS_RES_26,
        "filters":     json.dumps(filters),
        "limit":       CUSTOMS_LIMIT,
    }
    r = requests.get(CUSTOMS_API, params=params, timeout=30)
    r.raise_for_status()
    records = r.json().get("result", {}).get("records", [])
    _customs_cache[cache_key] = records
    return records


def prefetch_customs_for_notifications(notifications: list[dict]) -> None:
    """טוען מראש שאילתות ממוקדות (chapter × origin_iso) לכל ההתראות."""
    # אוספים את כל הצירופים הייחודיים
    combos: set[tuple[str, str | None]] = set()
    for n in notifications:
        cat_obj = n.get("productCategory") or {}
        cat = cat_obj.get("description", "") if cat_obj else ""
        chapters = get_hs_chapters(cat)
        iso_codes = _extract_iso_codes(n)
        if not chapters:
            continue
        if iso_codes:
            for ch in chapters:
                for iso in iso_codes:
                    combos.add((ch, iso))
        else:
            for ch in chapters:
                combos.add((ch, None))

    print(f"[Customs] שולף {len(combos)} צירופי (פרק, מדינה)...")
    for i, (ch, iso) in enumerate(sorted(combos)):
        recs = fetch_customs(ch, iso)
        label = f"פרק {ch}" + (f" × {iso}" if iso else " (כל מדינה)")
        print(f"  {label}: {len(recs)} רשומות")
        if (i + 1) % 5 == 0:
            time.sleep(0.3)


# ── מיפוי והצלבה ────────────────────────────────────────────────────────────

def normalize_category(raw: str) -> str:
    return (raw or "").strip().lower()


def get_hs_chapters(category_raw: str) -> list[str]:
    return CATEGORY_TO_HS_CHAPTERS.get(normalize_category(category_raw), [])


def _extract_iso_codes(notification: dict) -> set[str]:
    """מחלץ קודי ISO של מדינות מקור מהתראת RASFF."""
    origin_obj = (
        notification.get("originCountries")
        or notification.get("originCountry")
        or {}
    )
    if isinstance(origin_obj, list):
        codes = {c.get("isoCode", "") for c in origin_obj if c}
    elif isinstance(origin_obj, dict):
        codes = {origin_obj.get("isoCode", "")}
    else:
        codes = set()
    codes.discard("")
    return codes


def cross_match(notification: dict) -> list[dict]:
    """
    מצליב התראת RASFF אחת מול נתוני מכס ממוקדים (chapter × origin_iso).
    מחזיר רשימה מאוגדת: התראה × פרק HS × סיכום יבוא (לא שורה לכל רשומה).
    """
    cat_obj = notification.get("productCategory") or {}
    cat_desc = cat_obj.get("description", "") if cat_obj else ""
    chapters = get_hs_chapters(cat_desc)
    if not chapters:
        return []

    rasff_iso_codes = _extract_iso_codes(notification)

    matches = []
    seen: set[tuple] = set()   # מניעת כפילויות (reference, chapter, origin)

    for chapter in chapters:
        # אם יש מדינות מקור ב-RASFF — מחפשים רק אותן
        iso_list = list(rasff_iso_codes) if rasff_iso_codes else [None]
        for iso in iso_list:
            cache_key = f"{chapter}:{iso}" if iso else chapter
            records = _customs_cache.get(cache_key, [])

            if not records:
                continue

            # מאגד לפי (chapter, origin_iso)
            total_qty = sum(float(r.get("Quantity") or 0) for r in records)
            total_val = sum(float(r.get("NISCurrencyAmount") or 0) for r in records)
            hs8_codes  = list({r.get("CustomsItem_8_Digits", "") for r in records} - {""})
            ports      = list({r.get("CustomsHouse", "") for r in records} - {""})
            currencies = list({r.get("CurrencyCode", "") for r in records} - {""})

            origin_match = iso in rasff_iso_codes if iso else False
            confidence   = 0.85 if origin_match else 0.4

            dedup_key = (notification.get("reference", ""), chapter, iso or "")
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            matches.append({
                "rasff_reference":       notification.get("reference", ""),
                "rasff_subject":         notification.get("subject", ""),
                "rasff_category":        cat_desc,
                "rasff_date":            notification.get("ecValidationDate", ""),
                "rasff_classification":  (notification.get("notificationClassification") or {}).get("description", ""),
                "rasff_risk":            (notification.get("riskDecision") or {}).get("description", ""),
                "rasff_origin_countries": list(rasff_iso_codes),
                "customs_hs2":           chapter,
                "customs_hs8_codes":     hs8_codes,
                "customs_origin":        iso or "",
                "customs_records_count": len(records),
                "customs_total_qty_kg":  total_qty,
                "customs_total_value":   total_val,
                "customs_currency":      currencies[0] if len(currencies) == 1 else str(currencies),
                "customs_ports":         ports,
                "origin_match":          origin_match,
                "confidence":            confidence,
            })

    return matches


# ── אורכסטרציה ──────────────────────────────────────────────────────────────

def run_pipeline():
    print("=" * 60)
    print("RASFF-Israel Pipeline")
    print(f"זמן הרצה: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 60)

    # 1. שליפת RASFF
    notifications = fetch_rasff_recent(PAGES_TO_FETCH)

    # 2. טעינת נתוני מכס ממוקדים (פרק × מדינה)
    prefetch_customs_for_notifications(notifications)
    print()

    # 4. הצלבה
    print("[Cross-match] מצליב...")
    all_matches: list[dict] = []
    skipped = 0
    for n in notifications:
        matches = cross_match(n)
        if matches:
            all_matches.extend(matches)
        else:
            skipped += 1

    # 5. מיון לפי confidence ואחר כך תאריך
    all_matches.sort(key=lambda m: (-m["confidence"], m["rasff_date"]), reverse=False)
    all_matches.sort(key=lambda m: -m["confidence"])

    # 6. סטטיסטיקות
    high_conf   = [m for m in all_matches if m["confidence"] >= 0.8]
    origin_hits = [m for m in all_matches if m["origin_match"]]

    print(f"  סה\"כ התאמות: {len(all_matches)}")
    print(f"  התאמות עם מדינת מקור תואמת (confidence>=0.85): {len(origin_hits)}")
    print(f"  התאמות ללא נתוני מכס / קטגוריה לא ממופית: {skipped} התראות")

    # 7. שמירת JSON
    output = {
        "generated_at": datetime.now().isoformat(),
        "rasff_total_fetched": len(notifications),
        "matches_total": len(all_matches),
        "matches_high_confidence": len(high_conf),
        "matches": all_matches,
    }
    out_path = "data/results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[Done] שמור ל-{out_path}")

    # 8. תצוגה מקדימה של TOP 10 ממצאים
    print("\n--- TOP 10 התאמות בביטחון גבוה ---")
    shown = 0
    for m in all_matches:
        if not m["origin_match"]:
            continue
        hs_codes = ", ".join(m.get("customs_hs8_codes", []))
        print(f"  [{m['rasff_reference']}] {m['rasff_subject'][:60]}")
        print(f"    קטגוריה: {m['rasff_category']} | HS: {hs_codes} | מקור: {m['customs_origin']}")
        print(f"    כמות: {m['customs_total_qty_kg']:,.0f} ק\"ג | ערך: {m['customs_total_value']:,.0f} {m['customs_currency']} | confidence: {m['confidence']}")
        print()
        shown += 1
        if shown >= 10:
            break

    if shown == 0:
        print("  (אין התאמות עם origin_match בנתונים האחרונים)")


if __name__ == "__main__":
    run_pipeline()
