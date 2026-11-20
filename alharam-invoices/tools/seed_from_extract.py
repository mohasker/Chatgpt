"""Convert the Excel extract (seed.json from extract_excel.py) into database
documents for the invoicing system: one JSON file per document.

Usage: python3 seed_from_extract.py seed.json out_dir
Writes out_dir/customers/<id>.json, out_dir/invoices/<id>.json and a
manifest.json listing [collection, doc_id, path] for the import.
"""
import json, re, sys
from datetime import date, timedelta
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
seed = json.loads(src.read_text(encoding="utf-8"))
NOW = "2026-11-20T00:00:00Z"
DISCOUNT_LABELS = re.compile(r"^(dis|discount|discout|adjust)", re.I)


def r2(x):
    return round(float(x or 0) + 1e-9, 2)


def slug(s):
    a = re.sub(r"\s+", "-", str(s).strip())
    a = re.sub(r"[^A-Za-z0-9_\-.~:@+]", "", a).strip("-")
    return a


manifest = []
(out / "customers").mkdir(parents=True, exist_ok=True)
(out / "invoices").mkdir(parents=True, exist_ok=True)

customers = {}
for c in seed["customers"]:
    cid = c["id"]
    name = (c.get("name") or "").strip()
    doc = {
        "serial": c["serial"], "name": name,
        "nameEn": name if name and all(ord(ch) < 128 for ch in name) else "",
        "address": c.get("address") or "", "phone": c.get("phone") or "",
        "pobox": c.get("pobox") or "", "contact": c.get("contact") or "",
        "createdAt": NOW, "imported": True,
    }
    customers[c["serial"]] = (cid, doc)
    (out / "customers" / f"{cid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    manifest.append(["customers", cid, f"customers/{cid}.json"])

used, problems = set(), []
for inv in seed["invoices"]:
    no = str(inv["no"]).strip()
    iid = slug(no) or f"legacy-{inv['date'][:4]}-{inv['sheet'] and len(used)}"
    if not slug(no):
        iid = f"legacy-{inv['date']}"
    if iid in used:  # e.g. "ALH-26-0201 -" duplicates "ALH-26-0201"
        no = f"{no.rstrip(' -')}-B"
        iid = slug(no)
    used.add(iid)

    lines = []
    for l in inv["lines"]:
        if l.get("heading"):
            lines.append({"desc": l.get("desc") or "", "heading": True})
        else:
            lines.append({"desc": l.get("desc") or "", "unit": l.get("unit") or "",
                          "qty": l.get("qty"), "price": l.get("price"),
                          **({"amount": l["amount"]} if l.get("qty") is None and l.get("price") is None else {})})

    sub = r2(sum(
        0 if l.get("heading") else
        (l.get("amount") or 0) if l.get("qty") is None and l.get("price") is None else
        (l.get("price") or 0) if l.get("qty") is None else (l["qty"] * (l.get("price") or 0))
        for l in lines))
    target = r2(inv["total"])

    deductions, discount = [], 0.0
    rows = inv.get("summaryRows") or []
    progress = [r for r in rows if re.search(r"work done", r["label"], re.I)]
    if progress:  # progress billing: bill a percentage of the contract value
        value = r2(progress[0]["amount"])
        pct = re.search(r"(\d+)\s*%", progress[0]["label"])
        lbl = f"Less: Work not yet invoiced ({100 - int(pct.group(1))}%)" if pct else "Less: Work not yet invoiced"
        deductions.append({"label": lbl, "pct": None, "amount": r2(sub - value)})
        for r in rows:
            if re.search(r"retention", r["label"], re.I):
                deductions.append({"label": r["label"], "pct": None, "amount": r2(r["amount"])})
    else:
        for r in rows:
            if DISCOUNT_LABELS.match(r["label"].strip()):
                discount += r2(r["amount"])
            else:
                deductions.append({"label": r["label"], "pct": None, "amount": r2(r["amount"])})
    computed = r2(sub - sum(d["amount"] for d in deductions) - discount)
    if abs(computed - target) > 0.001:
        discount = r2(discount + computed - target)
        if abs(computed - target) > 1:
            problems.append(f"{no}: computed {computed} vs Excel {target}")
    discount = r2(discount)

    serial = inv["customerSerial"]
    cid, c = customers.get(serial, (f"c{serial}", {"name": inv.get("customerName") or ""}))
    d = inv["date"]
    kind = "proforma" if inv.get("proforma") else "invoice"
    due = (date.fromisoformat(d) + timedelta(days=30)).isoformat() if kind == "invoice" else ""
    doc = {
        "no": no, "kind": kind, "date": d, "dueDate": due, "year": int(d[:4]),
        "customerId": cid, "customerName": c.get("name", ""), "customerNameEn": c.get("nameEn", ""),
        "customerAddress": c.get("address", ""), "customerPhone": c.get("phone", ""), "customerPobox": c.get("pobox", ""),
        "ref": "", "workOrder": "", "location": "", "site": "", "typeOfWorks": "", "completedDate": d,
        "warranty": "1 Year", "worksList": "", "notes": f"مستوردة من ملف Excel (الورقة: {inv['sheet']})",
        "lines": lines, "deductions": deductions, "discount": discount,
        "subtotal": sub, "total": target, "paid": 0, "balance": target,
        "payments": [], "linked": [], "status": "issued", "excluded": kind != "invoice",
        "imported": True, "sheet": inv["sheet"], "createdAt": NOW, "updatedAt": NOW,
        "history": [{"at": NOW, "by": "", "action": "استيراد من ملف Excel"}],
    }
    (out / "invoices" / f"{iid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    manifest.append(["invoices", iid, f"invoices/{iid}.json"])

(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=0), encoding="utf-8")
print(f"{len(customers)} customers, {len(used)} invoices -> {out}")
for p in problems:
    print("CHECK:", p)
