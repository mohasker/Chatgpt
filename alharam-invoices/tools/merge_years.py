"""Merge extra yearly Excel extracts into the database seed, without duplicates.

Usage: python3 merge_years.py base_seed.json out_dir extract2023.json [extract2024.json ...]

- Customers are matched across workbooks by normalised name (serials differ per year);
  unknown names become new customers with ids c-y<year>-<serial>.
- Invoices already present (same number, in the base seed or an earlier file) are skipped;
  if the same number appears with a different total it is kept with a "-<year>" suffix and reported.
- Output: out_dir/customers/*.json, out_dir/invoices/*.json, out_dir/manifest.json (new docs only).
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

base = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2]); files = sys.argv[3:]
(out / "customers").mkdir(parents=True, exist_ok=True); (out / "invoices").mkdir(parents=True, exist_ok=True)


def norm(s):
    s = re.sub(r"[\s.\-–—_,()]+", " ", str(s or "")).strip().lower()
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return s


def slug(s):
    return re.sub(r"[^A-Za-z0-9_\-.~:@+]", "", re.sub(r"\s+", "-", str(s).strip())).strip("-")


by_name = {norm(c["name"]): c["id"] for c in base["customers"]}
cust_docs = {c["id"]: c for c in base["customers"]}
seen = {}  # no -> total
for inv in base["invoices"]:
    seen[str(inv["no"]).strip()] = round(inv["total"], 2)
seen_ids = {slug(n) or "legacy" for n in seen}
seen_ids |= {"legacy-2017-02-28", "ALH-26-0201-B"}

manifest, report = [], []
NOW = "2026-11-20T00:00:00Z"
from datetime import date, timedelta  # noqa: E402

for f in files:
    d = json.loads(Path(f).read_text(encoding="utf-8"))
    year = re.search(r"(20\d\d)", Path(f).name).group(1)
    serial_map = {}
    for c in d["customers"]:
        k = norm(c["name"])
        if not k:
            continue
        if k in by_name:
            cid = by_name[k]
            old = cust_docs.get(cid, {})
            # fill blanks from older workbooks
            upd = {f2: c.get(f2) for f2 in ("address", "phone", "pobox", "contact") if c.get(f2) and not old.get(f2)}
            if upd and cid.startswith("c-y"):
                old.update(upd)
        else:
            cid = f"c-y{year}-{c['serial']}"
            doc = {"serial": None, "name": c["name"].strip(), "nameEn": c["name"].strip() if all(ord(ch) < 128 for ch in c["name"]) else "",
                   "address": c.get("address") or "", "phone": c.get("phone") or "", "pobox": c.get("pobox") or "", "contact": c.get("contact") or "",
                   "createdAt": NOW, "imported": True, "sourceYear": int(year)}
            cust_docs[cid] = doc; by_name[k] = cid
            (out / "customers" / f"{cid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            manifest.append(["customers", cid, f"customers/{cid}.json"])
        serial_map[c["serial"]] = cid

    for inv in d["invoices"]:
        no = str(inv["no"]).strip()
        tot = round(inv["total"], 2)
        if no in seen:
            if abs(seen[no] - tot) < 0.01:
                continue
            report.append(f"{year}: {no} exists with total {seen[no]} — this file has {tot}; kept as {no}-{year}")
            no = f"{no}-{year}"
        seen[no] = tot
        iid = slug(no) or f"legacy-{inv['date']}"
        while iid in seen_ids:
            iid += "-x"
        seen_ids.add(iid)
        cid = serial_map.get(inv["customerSerial"])
        if not cid:
            k = norm(inv.get("customerName"))
            cid = by_name.get(k, "")
        c = cust_docs.get(cid, {"name": inv.get("customerName") or ""})
        lines = []
        for l in inv["lines"]:
            if l.get("heading"):
                lines.append({"desc": l.get("desc") or "", "heading": True})
            else:
                e = {"desc": l.get("desc") or "", "unit": l.get("unit") or "", "qty": l.get("qty"), "price": l.get("price")}
                if l.get("qty") is None and l.get("price") is None:
                    e["amount"] = l.get("amount")
                lines.append(e)
        sub = round(sum(0 if l.get("heading") else (l.get("amount") or 0) if l.get("qty") is None and l.get("price") is None
                        else (l.get("price") or 0) if l.get("qty") is None else l["qty"] * (l.get("price") or 0) for l in lines), 2)
        deductions, discount = [], 0.0
        for r in inv.get("summaryRows") or []:
            if re.match(r"^(dis|discount|discout|adjust)", r["label"].strip(), re.I):
                discount += r["amount"]
            else:
                deductions.append({"label": r["label"], "pct": None, "amount": round(r["amount"], 2)})
        comp = round(sub - sum(x["amount"] for x in deductions) - discount, 2)
        if abs(comp - tot) > 0.001:
            discount = round(discount + comp - tot, 2)
            if abs(comp - tot) > 1:
                report.append(f"{year}: {no} computed {comp} vs Excel {tot} (difference put in discount)")
        dt = inv["date"]
        kind = "proforma" if inv.get("proforma") else "invoice"
        doc = {"no": no, "kind": kind, "date": dt, "dueDate": "", "year": int(dt[:4]),
               "customerId": cid, "customerName": c.get("name", ""), "customerNameEn": c.get("nameEn", ""),
               "customerAddress": c.get("address", ""), "customerPhone": c.get("phone", ""), "customerPobox": c.get("pobox", ""),
               "ref": "", "workOrder": "", "location": "", "site": "", "typeOfWorks": "", "completedDate": dt, "warrantyMonths": 12, "warranty": "1 Year",
               "worksList": "", "notes": f"مستوردة من ملف Excel {year} (الورقة: {inv['sheet']})",
               "lines": lines, "deductions": deductions, "discount": round(discount, 2),
               "subtotal": sub, "total": tot, "paid": 0, "balance": tot, "payments": [], "linked": [],
               "status": "issued", "excluded": kind != "invoice", "imported": True, "sourceYear": int(year), "sheet": inv["sheet"],
               "createdAt": NOW, "updatedAt": NOW, "history": [{"at": NOW, "by": "", "action": f"استيراد من ملف Excel {year}"}]}
        (out / "invoices" / f"{iid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        manifest.append(["invoices", iid, f"invoices/{iid}.json"])

(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
nc = sum(1 for m in manifest if m[0] == "customers"); ni = len(manifest) - nc
print(f"new customers {nc}, new invoices {ni}")
for r in report:
    print("CHECK:", r)
