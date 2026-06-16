"""
בדיקה מהירה: שאילתה ספציפית על תמ"ל לתינוקות.
מריצים: python quick_test.py
"""

import json
import sys
import httpx
import requests
import urllib3
urllib3.disable_warnings()

# תיקון קידוד עברית בטרמינל Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RASFF_URL   = "https://webgate.ec.europa.eu/rasff-window/backend/public/notification/search/consolidated/en/"
CUSTOMS_URL = "https://data.gov.il/api/3/action/datastore_search"
CUSTOMS_RES = "6b0a2694-889f-4908-94dc-4ead004d719a"   # 2026

RASFF_HEADERS = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":      "https://webgate.ec.europa.eu/rasff-window/screen/search",
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "Origin":       "https://webgate.ec.europa.eu",
}

# ── 1. RASFF: חיפוש "infant formula" ─────────────────────────────────────────

print("=" * 55)
print("1. RASFF — חיפוש 'infant formula'")
print("=" * 55)

rasff_body = {
    "parameters":               {"pageNumber": 1, "itemsPerPage": 10},
    "notificationReference":    None,
    "subject":                  "infant formula",
    "notifyingCountry":         None,
    "originCountry":            None,
    "distributionCountry":      None,
    "notificationType":         None,
    "notificationStatus":       None,
    "notificationClassification": None,
    "notificationBasis":        None,
    "productCategory":          None,
    "actionTaken":              None,
    "hazardCategory":           None,
    "riskDecision":             None,
}

with httpx.Client(verify=False, timeout=30) as client:
    r = client.post(RASFF_URL, json=rasff_body, headers=RASFF_HEADERS)

print(f"סטטוס: {r.status_code}")
data = r.json()
total    = data.get("totalElements", 0)
alerts   = data.get("notifications", [])
print(f"סה\"כ התראות על 'infant formula': {total}\n")

rasff_origins = set()
for a in alerts:
    ref   = a.get("reference", "")
    subj  = a.get("subject", "")
    date  = a.get("ecValidationDate", "")[:10]
    cat   = (a.get("productCategory") or {}).get("description", "")
    risk  = (a.get("riskDecision")    or {}).get("description", "")
    orig_list = a.get("originCountries") or []
    orig_iso  = orig_list[0].get("isoCode", "?") if orig_list else "?"
    orig_name = orig_list[0].get("organizationName", "") if orig_list else ""
    for o in orig_list:
        rasff_origins.add(o.get("isoCode", ""))
    print(f"  [{ref}] {date}")
    print(f"    {subj[:70]}")
    print(f"    קטגוריה: {cat} | סיכון: {risk} | מקור: {orig_name} ({orig_iso})")
    print()

# ── 2. Customs: HS 19011000 ───────────────────────────────────────────────────

print("=" * 55)
print("2. מכס ישראל — יבוא תמ\"ל (HS 19011000)")
print("=" * 55)

params = {
    "resource_id": CUSTOMS_RES,
    "filters":     json.dumps({"CustomsItem_8_Digits": "19011000"}),
    "limit":       50,
}
r2 = requests.get(CUSTOMS_URL, params=params, timeout=30)
print(f"סטטוס: {r2.status_code}")
result  = r2.json().get("result", {})
total_c = result.get("total", 0)
records = result.get("records", [])
print(f"סה\"כ רשומות יבוא: {total_c}\n")

customs_origins = set()
for rec in records:
    iso  = rec.get("Origin_Country", "")
    qty  = float(rec.get("Quantity", 0) or 0)
    val  = float(rec.get("NISCurrencyAmount", 0) or 0)
    cur  = rec.get("CurrencyCode", "")
    port = rec.get("CustomsHouse", "")
    mon  = rec.get("Month", "")
    yr   = rec.get("Year", "")
    customs_origins.add(iso)
    print(f"  {mon:>2}/{yr} | מקור: {iso} | {qty:>10,.0f} ק\"ג | {val:>12,.0f} {cur} | {port}")

# ── 3. הצלבה ─────────────────────────────────────────────────────────────────

print()
print("=" * 55)
print("3. הצלבה: מקורות RASFF מול מקורות מכס")
print("=" * 55)

overlap = rasff_origins & customs_origins
rasff_origins.discard("?")

if overlap:
    print(f"\nHIT! מדינות שיש עליהן גם אזהרת RASFF וגם יבוא לישראל:")
    for iso in sorted(overlap):
        # סכם יבוא מאותה מדינה
        recs_from = [r for r in records if r.get("Origin_Country") == iso]
        total_qty = sum(float(r.get("Quantity", 0) or 0) for r in recs_from)
        total_val = sum(float(r.get("NISCurrencyAmount", 0) or 0) for r in recs_from)
        cur = recs_from[0].get("CurrencyCode", "") if recs_from else ""
        print(f"  {iso}: {total_qty:,.0f} ק\"ג | {total_val:,.0f} {cur}")
    print()
    # הצג את ההתראות הרלוונטיות
    print("התראות RASFF על מוצרים שישראל מייבאת מאותה מדינה:\n")
    for a in alerts:
        orig_list = a.get("originCountries") or []
        orig_isos = {o.get("isoCode", "") for o in orig_list}
        if orig_isos & overlap:
            ref  = a.get("reference", "")
            subj = a.get("subject", "")
            risk = (a.get("riskDecision") or {}).get("description", "")
            orig_names = ", ".join(o.get("organizationName","") for o in orig_list if o.get("isoCode","") in overlap)
            print(f"  => [{ref}] {subj[:65]}")
            print(f"     מקור: {orig_names} | סיכון: {risk}")
else:
    rasff_str   = ", ".join(sorted(rasff_origins)) or "אין"
    customs_str = ", ".join(sorted(customs_origins)) or "אין"
    print(f"\nאין חפיפה ישירה בין מקורות ה-10 ההתראות ולמקורות היבוא.")
    print(f"  מקורות RASFF:  {rasff_str}")
    print(f"  מקורות יבוא:   {customs_str}")
    print(f"\n(ייתכן שיש חפיפה ב-{total - 10} ההתראות הנוספות שלא נשלפו)")
