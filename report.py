"""
מייצר דשבורד HTML של הצלבת RASFF × מכס ישראל ופותח בדפדפן.
הרצה: python report.py [מחרוזת-חיפוש]
ברירת מחדל: infant formula
"""

import json, sys, os, webbrowser, textwrap
from datetime import datetime
import httpx, requests, urllib3
urllib3.disable_warnings()

QUERY = " ".join(sys.argv[1:]) or "infant formula"

RASFF_URL   = "https://webgate.ec.europa.eu/rasff-window/backend/public/notification/search/consolidated/en/"
CUSTOMS_URL = "https://data.gov.il/api/3/action/datastore_search"
CUSTOMS_RES = "6b0a2694-889f-4908-94dc-4ead004d719a"
RASFF_H = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":      "https://webgate.ec.europa.eu/rasff-window/screen/search",
    "Content-Type": "application/json",
    "Accept":       "application/json",
    "Origin":       "https://webgate.ec.europa.eu",
}

# ── שליפת נתונים ─────────────────────────────────────────────────────────────

def fetch_rasff(query, pages=2):
    alerts = []
    with httpx.Client(verify=False, timeout=30) as c:
        for page in range(1, pages + 1):
            body = {k: None for k in ["notificationReference","subject","notifyingCountry",
                    "originCountry","distributionCountry","notificationType","notificationStatus",
                    "notificationClassification","notificationBasis","productCategory",
                    "actionTaken","hazardCategory","riskDecision"]}
            body["parameters"] = {"pageNumber": page, "itemsPerPage": 50}
            body["subject"] = query
            r = c.post(RASFF_URL, json=body, headers=RASFF_H)
            r.raise_for_status()
            d = r.json()
            alerts.extend(d.get("notifications", []))
            if len(d.get("notifications", [])) < 50:
                break
    return alerts

def fetch_customs_for_iso(iso, hs2_list):
    """שולף יבוא לפי מדינת מקור + פרקי HS."""
    records = []
    for hs2 in hs2_list:
        params = {
            "resource_id": CUSTOMS_RES,
            "filters":     json.dumps({"CustomsItem_2_Digits": hs2, "Origin_Country": iso}),
            "limit":       500,
        }
        r = requests.get(CUSTOMS_URL, params=params, timeout=30)
        r.raise_for_status()
        records.extend(r.json().get("result", {}).get("records", []))
    return records

# HS chapters לפי קטגוריית RASFF
CAT_HS = {
    "milk and milk products":                               ["04", "19"],
    "dietetic foods, food supplements and fortified foods": ["04", "19", "21"],
    "cereals and bakery products":                          ["10", "11", "19"],
    "meat and meat products (other than poultry)":          ["02", "16"],
    "poultry meat and poultry meat products":               ["02", "16"],
    "fish and fish products":                               ["03", "16"],
    "fruits and vegetables":                                ["07", "08"],
    "nuts, nut products and seeds":                         ["08", "12"],
    "herbs and spices":                                     ["09"],
    "confectionery":                                        ["17", "18"],
    "cocoa and cocoa preparations, coffee and tea":         ["09", "18"],
    "eggs and egg products":                                ["04"],
    "prepared dishes and snacks":                           ["16", "19", "21"],
    "soups, broths, sauces and condiments":                 ["21"],
    "other food product / mixed":                           ["21"],
}

# ── הצלבה ────────────────────────────────────────────────────────────────────

print(f"[1/3] שולף RASFF: '{QUERY}'...")
alerts = fetch_rasff(QUERY)
total_rasff = alerts[0] and None  # sentinel
with httpx.Client(verify=False, timeout=10) as c:
    body = {k: None for k in ["notificationReference","subject","notifyingCountry",
            "originCountry","distributionCountry","notificationType","notificationStatus",
            "notificationClassification","notificationBasis","productCategory",
            "actionTaken","hazardCategory","riskDecision"]}
    body["parameters"] = {"pageNumber": 1, "itemsPerPage": 1}
    body["subject"] = QUERY
    r = c.post(RASFF_URL, json=body, headers=RASFF_H)
    total_rasff = r.json().get("totalElements", len(alerts))

print(f"    {len(alerts)} התראות נשלפו (סה\"כ ב-RASFF: {total_rasff})")

print("[2/3] מצליב מול מכס...")
rows = []
seen_customs = {}   # iso → records cache

for a in alerts:
    cat_obj  = a.get("productCategory") or {}
    cat      = (cat_obj.get("description") or "").lower()
    hs_list  = CAT_HS.get(cat, [])
    orig_list = a.get("originCountries") or []
    risk_obj  = a.get("riskDecision") or {}
    clf_obj   = a.get("notificationClassification") or {}

    alert_info = {
        "ref":      a.get("reference", ""),
        "notif_id": a.get("notifId", ""),
        "subject":  a.get("subject", ""),
        "date":     (a.get("ecValidationDate") or "")[:10],
        "category": cat_obj.get("description", ""),
        "risk":     risk_obj.get("description", ""),
        "classification": clf_obj.get("description", ""),
    }

    for orig in orig_list:
        iso  = orig.get("isoCode", "")
        name = orig.get("organizationName", iso)
        if not iso or not hs_list:
            continue

        cache_key = f"{iso}|{'|'.join(hs_list)}"
        if cache_key not in seen_customs:
            seen_customs[cache_key] = fetch_customs_for_iso(iso, hs_list)
        customs = seen_customs[cache_key]

        if not customs:
            continue

        total_kg  = sum(float(r.get("Quantity") or 0) for r in customs)
        total_val = sum(float(r.get("NISCurrencyAmount") or 0) for r in customs)
        curs      = list({r.get("CurrencyCode","") for r in customs} - {""})
        ports     = list({r.get("CustomsHouse","") for r in customs} - {""})
        hs8s      = sorted({r.get("CustomsItem_8_Digits","") for r in customs} - {""})

        rows.append({
            **alert_info,
            "origin_iso":   iso,
            "origin_name":  name,
            "total_kg":     total_kg,
            "total_val":    total_val,
            "currency":     curs[0] if len(curs) == 1 else "מעורב",
            "ports":        ports,
            "hs8_codes":    hs8s,
            "records_n":    len(customs),
        })

rows.sort(key=lambda r: (
    {"serious": 0, "potentially serious": 1}.get(r["risk"], 2),
    -r["total_kg"]
))
print(f"    {len(rows)} שורות התאמה")

# ── HTML ──────────────────────────────────────────────────────────────────────

RISK_COLOR = {
    "serious":            "#c0392b",
    "potentially serious":"#e67e22",
    "not serious":        "#27ae60",
    "no risk":            "#95a5a6",
}
RISK_BG = {
    "serious":            "#fdecea",
    "potentially serious":"#fef5ec",
    "not serious":        "#eafaf1",
    "no risk":            "#f5f5f5",
}

def risk_badge(risk):
    color = RISK_COLOR.get(risk, "#888")
    label = risk or "לא ידוע"
    return f'<span class="badge" style="background:{color}">{label}</span>'

def hs_chips(codes):
    return " ".join(f'<code class="hs">{c}</code>' for c in codes[:6])

def fmt_kg(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M ק\"ג"
    if v >= 1_000:     return f"{v/1_000:.0f}K ק\"ג"
    return f"{v:.0f} ק\"ג"

def fmt_val(v, cur):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M {cur}"
    if v >= 1_000:     return f"{v/1_000:.0f}K {cur}"
    return f"{v:.0f} {cur}"

summary_risk = {}
for r in rows:
    summary_risk[r["risk"]] = summary_risk.get(r["risk"], 0) + 1

table_rows = ""
for r in rows:
    risk  = r["risk"]
    bg    = RISK_BG.get(risk, "#fff")
    ports_str = ", ".join(r["ports"][:3])
    table_rows += f"""
    <tr style="background:{bg}">
      <td class="ref"><a href="https://webgate.ec.europa.eu/rasff-window/screen/notification/{r['notif_id']}"
          target="_blank">{r['ref']}</a><br><small>{r['date']}</small></td>
      <td class="subject">{r['subject']}</td>
      <td>{risk_badge(risk)}</td>
      <td class="country"><strong>{r['origin_name']}</strong></td>
      <td class="nums">{fmt_kg(r['total_kg'])}<br><small>{fmt_val(r['total_val'], r['currency'])}</small></td>
      <td class="ports"><small>{ports_str}</small></td>
      <td class="hs-cell"><small>{hs_chips(r['hs8_codes'])}</small></td>
    </tr>"""

summary_pills = ""
for risk, count in sorted(summary_risk.items(), key=lambda x: {"serious":0,"potentially serious":1}.get(x[0],2)):
    color = RISK_COLOR.get(risk, "#888")
    summary_pills += f'<span class="sum-pill" style="border-color:{color};color:{color}"><strong>{count}</strong> {risk}</span>'

now = datetime.now().strftime("%d/%m/%Y %H:%M")

html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RASFF × מכס ישראל — {QUERY}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; color: #222; font-size: 14px; }}

  header {{ background: #1a3a5c; color: #fff; padding: 18px 28px; display: flex; align-items: center; gap: 16px; }}
  header h1 {{ font-size: 1.3rem; font-weight: 700; }}
  header .query {{ background: rgba(255,255,255,.15); border-radius: 6px; padding: 4px 12px; font-size: 0.95rem; }}
  header .meta {{ margin-right: auto; font-size: 0.8rem; opacity: .7; text-align: left; direction: ltr; }}

  .container {{ max-width: 1300px; margin: 0 auto; padding: 20px 16px; }}

  .stats {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 20px; }}
  .stat-card {{ background: #fff; border-radius: 10px; padding: 14px 20px; flex: 1; min-width: 160px;
               box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .stat-card .num {{ font-size: 1.8rem; font-weight: 700; color: #1a3a5c; }}
  .stat-card .lbl {{ font-size: 0.78rem; color: #666; margin-top: 2px; }}

  .summary-pills {{ background: #fff; border-radius: 10px; padding: 14px 20px; margin-bottom: 20px;
                    box-shadow: 0 1px 4px rgba(0,0,0,.08); display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
  .sum-pill {{ border: 1.5px solid; border-radius: 20px; padding: 4px 14px; font-size: 0.82rem; }}

  .table-wrap {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #1a3a5c; color: #fff; padding: 10px 12px; text-align: right; font-weight: 600;
        font-size: 0.82rem; white-space: nowrap; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #eee; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(0,0,0,.02) !important; }}

  .ref a {{ color: #1a3a5c; font-weight: 600; text-decoration: none; font-size: 0.82rem; }}
  .ref a:hover {{ text-decoration: underline; }}
  .subject {{ max-width: 280px; line-height: 1.4; }}
  .nums {{ text-align: left; direction: ltr; white-space: nowrap; }}
  .ports {{ color: #555; }}
  .hs-cell {{ max-width: 180px; }}

  .badge {{ display: inline-block; color: #fff; border-radius: 12px; padding: 2px 10px;
             font-size: 0.75rem; font-weight: 600; white-space: nowrap; }}
  code.hs {{ background: #eef; color: #336; border-radius: 4px; padding: 1px 5px;
              font-size: 0.72rem; display: inline-block; margin: 1px; }}
  .country {{ white-space: nowrap; }}

  .footer {{ text-align: center; color: #999; font-size: 0.75rem; margin: 24px 0 8px; }}
  .no-data {{ text-align: center; padding: 40px; color: #888; }}
</style>
</head>
<body>
<header>
  <div>
    <div style="font-size:.75rem;opacity:.6;margin-bottom:4px">RASFF × מכס ישראל</div>
    <h1>🔍 חיפוש: <span class="query">{QUERY}</span></h1>
  </div>
  <div class="meta">עודכן: {now}<br>מקורות: RASFF + data.gov.il</div>
</header>

<div class="container">

  <div class="stats">
    <div class="stat-card">
      <div class="num">{total_rasff}</div>
      <div class="lbl">התראות RASFF על "{QUERY}"</div>
    </div>
    <div class="stat-card">
      <div class="num">{len(alerts)}</div>
      <div class="lbl">נשלפו לניתוח</div>
    </div>
    <div class="stat-card">
      <div class="num">{len(rows)}</div>
      <div class="lbl">הצלבות עם יבוא ישראל</div>
    </div>
    <div class="stat-card">
      <div class="num" style="color:#c0392b">{summary_risk.get('serious',0)}</div>
      <div class="lbl">חומרה: serious</div>
    </div>
  </div>

  <div class="summary-pills">
    <span style="font-size:.82rem;color:#555;margin-left:4px">חלוקה לפי חומרה:</span>
    {summary_pills}
  </div>

  <div class="table-wrap">
    {'<table><thead><tr><th>מזהה RASFF</th><th>תיאור</th><th>חומרה</th><th>מדינת מקור</th><th>יבוא לישראל</th><th>נמלים</th><th>קודי HS</th></tr></thead><tbody>' + table_rows + '</tbody></table>' if rows else '<div class="no-data">לא נמצאו הצלבות</div>'}
  </div>

  <div class="footer">
    נתוני RASFF: <a href="https://webgate.ec.europa.eu/rasff-window/screen/search" target="_blank">RASFF Window</a> ·
    נתוני מכס: <a href="https://data.gov.il/he/datasets/taxes-authority/customs_import_statistics_data" target="_blank">data.gov.il</a>
  </div>
</div>
</body>
</html>"""

# ── שמירה ופתיחה ─────────────────────────────────────────────────────────────

print("[3/3] מייצר HTML ופותח בדפדפן...")
out = os.path.abspath("web/dashboard.html")
os.makedirs("web", exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

if sys.stdout.isatty():   # פותח דפדפן רק כשרץ אינטראקטיבי, לא ב-CI
    webbrowser.open(f"file:///{out.replace(os.sep, '/')}")
print(f"    נשמר ב: {out}")
