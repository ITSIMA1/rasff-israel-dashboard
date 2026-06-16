"""
בדיקת חיבור ל-RASFF ול-Customs API.
מריצים: python test_apis.py
"""

import json
import requests

CUSTOMS_RESOURCE_2026 = "6b0a2694-889f-4908-94dc-4ead004d719a"
CUSTOMS_API = "https://data.gov.il/api/3/action/datastore_search"
RASFF_URL = "https://webgate.ec.europa.eu/rasff-window/backend/public/notification/search/consolidated/en/"

RASFF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://webgate.ec.europa.eu/rasff-window/screen/search",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://webgate.ec.europa.eu",
}


def rasff_post(body):
    """שולח בקשת POST ל-RASFF ומחזיר תוצאה."""
    r = requests.post(RASFF_URL, json=body, headers=RASFF_HEADERS, verify=False, timeout=30)
    return r


def make_rasff_body(page=1, per_page=5, subject=None, product_category=None, origin_country=None):
    """בונה body לבקשת RASFF לפי הפורמט האמיתי שהתגלה מהפרוטוטייפ."""
    return {
        "parameters": {
            "pageNumber": page,
            "itemsPerPage": per_page,
        },
        "notificationReference": None,
        "subject": subject,
        "notifyingCountry": None,
        "originCountry": origin_country,
        "distributionCountry": None,
        "notificationType": None,
        "notificationStatus": None,
        "notificationClassification": None,
        "notificationBasis": None,
        "productCategory": product_category,
        "actionTaken": None,
        "hazardCategory": None,
        "riskDecision": None,
    }


def print_rasff_result(data):
    """מדפיס תוצאת RASFF בצורה קריאה."""
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (int, str, float, bool)):
                print(f"  {k} = {v}")
            elif isinstance(v, list):
                print(f"  {k}: {len(v)} פריטים")
                if v:
                    print("  דוגמה:", json.dumps(v[0], ensure_ascii=False, indent=2)[:800])
    elif isinstance(data, list):
        print(f"  רשימה של {len(data)} פריטים")
        if data:
            print("  דוגמה:", json.dumps(data[0], ensure_ascii=False, indent=2)[:800])


def test_rasff_unfiltered():
    """שולף 5 התראות אחרונות מ-RASFF ללא סינון — בדיקת זמינות בסיסית."""
    print("\n=== RASFF — ללא סינון (5 התראות אחרונות) ===")
    r = rasff_post(make_rasff_body(per_page=5))
    print(f"סטטוס: {r.status_code}")
    if r.status_code != 200:
        print("שגיאה:", r.text[:500])
        return False
    data = r.json()
    print("מפתחות בתשובה:", list(data.keys()) if isinstance(data, dict) else type(data))
    print_rasff_result(data)
    return True


def test_rasff_filtered_subject():
    """מנסה לסנן לפי subject חופשי."""
    print("\n=== RASFF — סינון לפי subject ('infant formula') ===")
    r = rasff_post(make_rasff_body(per_page=5, subject="infant formula"))
    print(f"סטטוס: {r.status_code}")
    if r.status_code != 200:
        print("תשובה:", r.text[:300])
        return
    data = r.json()
    print_rasff_result(data)


def test_rasff_filtered_category():
    """מנסה לסנן לפי קטגוריית מוצר."""
    print("\n=== RASFF — סינון לפי productCategory ===")
    # ננסה ערכים שונים של קטגוריה
    for cat_val in ["DIET", "MILK", "dietetic foods", "milk and milk products"]:
        r = rasff_post(make_rasff_body(per_page=3, product_category=cat_val))
        data = r.json() if r.status_code == 200 else {}
        total = None
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, int) and v > 0:
                    total = v
                    break
        items = None
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    items = len(v)
                    break
        print(f"  category='{cat_val}' → סטטוס {r.status_code} | תוצאות: {items} פריטים | total={total}")


def test_customs_infant_formula():
    """שולף רשומות יבוא תמ\"ל לתינוקות (HS 19011000) מנתוני המכס."""
    print("\n=== Customs API — תמ\"ל לתינוקות (HS 19011000) ===")
    params = {
        "resource_id": CUSTOMS_RESOURCE_2026,
        "filters": json.dumps({"CustomsItem_8_Digits": "19011000"}),
        "limit": 10,
    }
    r = requests.get(CUSTOMS_API, params=params, timeout=30)
    print(f"סטטוס: {r.status_code}")
    if r.status_code != 200:
        print("שגיאה:", r.text[:300])
        return

    data = r.json()
    result = data.get("result", {})
    total = result.get("total", "?")
    records = result.get("records", [])
    print(f"סה\"כ רשומות: {total}")
    for rec in records:
        print(f"  {rec.get('Month','?')}/{rec.get('Year','?')} | מקור: {rec.get('Origin_Country','?')} | "
              f"כמות: {float(rec.get('Quantity',0)):,.0f} {rec.get('Quantity_MeasurementUnitName','')} | "
              f"ערך: {float(rec.get('NISCurrencyAmount',0)):,.0f} {rec.get('CurrencyCode','')}")


def test_customs_chapter19():
    """שולף סטטיסטיקה לפרק 19 (תבשילי דגנים/קמח/חלב) — כדי לראות את ההיקף."""
    print("\n=== Customs API — פרק 19 (בדיקת היקף) ===")
    params = {
        "resource_id": CUSTOMS_RESOURCE_2026,
        "filters": json.dumps({"CustomsItem_2_Digits": "19"}),
        "limit": 1,
    }
    r = requests.get(CUSTOMS_API, params=params, timeout=30)
    print(f"סטטוס: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        total = data.get("result", {}).get("total", "?")
        print(f"סה\"כ רשומות בפרק 19: {total}")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    print("=" * 60)
    print("בדיקת APIs — RASFF + Customs Israel")
    print("=" * 60)

    rasff_ok = test_rasff_unfiltered()
    if rasff_ok:
        test_rasff_filtered_subject()
        test_rasff_filtered_category()

    test_customs_infant_formula()
    test_customs_chapter19()

    print("\n=== סיום בדיקות ===")
