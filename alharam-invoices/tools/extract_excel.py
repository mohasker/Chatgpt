import openpyxl, sys, json, re, datetime
from openpyxl.utils import get_column_letter
SRC=sys.argv[1]; OUT=sys.argv[2]
wbv=openpyxl.load_workbook(SRC,read_only=True,data_only=True)
wbf=openpyxl.load_workbook(SRC,read_only=True,data_only=False)
def grid(ws,maxc=14):
    g={}
    for r in ws.iter_rows(max_col=maxc):
        for c in r:
            if c.value is not None and hasattr(c,'row'): g[(c.row,c.column)]=c.value
    return g
def clean(v):
    if v is None: return None
    if isinstance(v,float) and v.is_integer(): v=int(v)
    s=re.sub(r'[ \t ]+',' ',str(v)); s=re.sub(r' *\n *','\n',s).strip()
    if s in ('','-','ـ','ــ','—','.'): return None
    return s
def num(v):
    if isinstance(v,bool): return None
    if isinstance(v,(int,float)): return v
    if isinstance(v,str):
        t=v.strip().replace(',','')
        try: return float(t)
        except: return None
    return None
def todate(v):
    if isinstance(v,datetime.datetime): return v.date().isoformat()
    if isinstance(v,datetime.date): return v.isoformat()
    if isinstance(v,(int,float)) and 20000<v<80000:
        return (datetime.date(1899,12,30)+datetime.timedelta(days=int(v))).isoformat()
    if isinstance(v,str):
        for f in ('%d/%m/%Y','%d-%m-%Y','%Y-%m-%d','%d.%m.%Y'):
            try: return datetime.datetime.strptime(v.strip(),f).date().isoformat()
            except: pass
    return None
r2=lambda x: round(x,2)
# customers
ws=wbv['Name']; g=grid(ws,8)
customers=[]; cmap={}
for r in sorted({k[0] for k in g if k[0]>=3}):
    ser=num(g.get((r,2)))
    if ser is None: continue
    ser=int(ser)
    c={"id":f"c{ser}","serial":ser,"name":clean(g.get((r,3))),"address":clean(g.get((r,4))),
       "phone":clean(g.get((r,5))),"pobox":clean(g.get((r,6))),"contact":clean(g.get((r,7)))}
    if not c["name"]: continue
    if ser in cmap: print("DUP customer serial",ser)
    customers.append(c); cmap[ser]=c
issues=[]; mism=[]; invoices=[]
def norm(s): return re.sub(r'\s+','',str(s)).lower()
for sn in wbv.sheetnames:
    if sn=='Name': continue
    try:
        g=grid(wbv[sn]); gf=grid(wbf[sn])
        gall=grid(wbv[sn],40)
        proforma=any(isinstance(v,str) and re.search(r'p[er]{1,2}forma',v,re.I) for (r,c),v in gall.items() if c<17)  # Q13 'Performa INVOICE' is template residue on nearly every sheet
        # header row
        hdr=None
        for (r,c),v in sorted(g.items()):
            if isinstance(v,str) and norm(v).startswith('description'):
                hdr=r; break
        if hdr is None: issues.append((sn,'no header row')); continue
        cols={}
        for (r,c),v in g.items():
            if r!=hdr or not isinstance(v,str): continue
            n=norm(v)
            if n.startswith('ser'): cols['ser']=c
            elif n.startswith('description'): cols['desc']=c
            elif n.startswith('unit.') or n.startswith('uom') or n=='unit': cols['unit']=c
            elif n.startswith('qty'): cols['qty']=c
            elif n.startswith('unitprice'): cols['price']=c
            elif 'total' in n: cols['amt']=c
        need={'desc','qty','price','amt'}-set(cols)
        if need: issues.append((sn,f'missing header cols {need}')); continue
        # labels: net = label with net/الصافي; total = first total-ish label after header
        lab={}
        for (r,c),v in sorted(g.items()):
            if not isinstance(v,str) or r<=hdr or c<cols['price']-2: continue
            n=norm(v)
            if n.startswith('net') or 'الصافي' in n:
                if 'total' in lab and 'net' not in lab: lab['net']=r
            elif ('total' in n or 'الإجم' in n) and 'total' not in lab: lab['total']=r
        tr=lab.get('total')
        if tr is None: issues.append((sn,'no Total row')); continue
        # date
        date=None
        for (r,c),v in g.items():
            if isinstance(v,str) and norm(v).startswith('date') and r<hdr:
                for cc in list(range(c+1,c+8))+list(range(c-1,0,-1)):
                    d=todate(g.get((r,cc)))
                    if d: date=d; break
                if date: break
        if not date: issues.append((sn,'no date'))
        aser=num(g.get((2,1)))
        aser=int(aser) if aser is not None else None
        lines=[]; calc=0.0
        unitc=cols.get('unit'); dend=(unitc or cols['qty'])
        for r in range(hdr+1,tr):
            dstart=cols['ser'] if 'ser' in cols and isinstance(g.get((r,cols['ser'])),str) else cols['desc']
            descs=[clean(g.get((r,c))) for c in range(dstart,dend)]
            descs=[d for d in descs if d]
            desc=' | '.join(descs) if descs else None
            unit=clean(g.get((r,unitc))) if unitc else None
            q=num(g.get((r,cols['qty']))); p=num(g.get((r,cols['price']))); a=num(g.get((r,cols['amt'])))
            serv=g.get((r,cols['ser'])) if 'ser' in cols else None
            if not desc and q is None and p is None and a is None and unit is None: continue
            heading = q is None and p is None
            comp=q*p if (q is not None and p is not None) else None
            if comp is not None: calc+=comp
            if a is not None and comp is not None and abs(a-comp)>0.01:
                mism.append(f"{sn} r{r}: cached {a} vs qty*price {r2(comp)}")
            if a is not None and comp is None and abs(a)>0.001:
                issues.append((sn,f"r{r}: lump-sum amount {a} with no qty/price ({desc!r:.45})")); calc+=a
            if comp is not None and a is None:
                ff=gf.get((r,cols['amt']))
                mism.append(f"{sn} r{r}: no cached line total (formula={ff!r}); computed {r2(comp)}")
            if not desc: issues.append((sn,f'r{r} line without description')) 
            amt=a if a is not None else comp
            if amt is not None: heading=False
            lines.append({"desc":desc,"unit":unit,"qty":q,"price":p,"amount":None if amt is None else r2(amt),"heading":heading,"_cached":a is not None})
        amtc=cols['amt']
        def labval(key):
            r=lab.get(key)
            if r is None: return None
            for c in (amtc,amtc+1,amtc-1):
                v=num(g.get((r,c)))
                if v is not None: return v
            return None
        sub=labval('total')
        if sub is None: sub=calc; issues.append((sn,'no cached subtotal; used computed'))
        # lines with qty*price but no cached amount, when cached amounts alone equal subtotal -> informational
        cached_sum=sum(l['amount'] for l in lines if l['_cached'] and l['amount'] is not None)
        if abs(sub-calc)>0.01 and abs(sub-cached_sum)<=0.01:
            for l in lines:
                if not l['_cached'] and l['amount'] is not None:
                    mism.append(f"{sn}: line {l['desc']!r:.50} qty*price={l['amount']} has no amount cell; excluded from total (subtotal matches cached amounts) -> marked heading")
                    l['heading']=True; l['amount']=None
            calc=cached_sum
        if abs(sub-calc)>0.01: mism.append(f"{sn}: cached subtotal {sub} vs computed lines {r2(calc)}")
        net=labval('net')
        adjustments=[]
        if net is None:
            net=sub; issues.append((sn,'no net row; total=subtotal'))
        else:
            for r in range(lab['total']+1,lab['net']):
                v=None
                for c in (amtc,amtc+1):
                    v=num(g.get((r,c)))
                    if v is not None: break
                if v is None or abs(v)<1e-9 or abs(v-sub)<0.005: continue
                lbl=' '.join(x for x in (clean(g.get((r,c))) for c in range(cols['desc'],amtc)) if x and num(x) is None) or 'Adjustment'
                adjustments.append({"label":lbl,"amount":r2(v)})
        dis=sub-net
        if abs(dis-sum(a['amount'] for a in adjustments))>0.01:
            issues.append((sn,f'progress-billing summary (sub {r2(sub)} -> net {r2(net)}): {adjustments}'))
        for l in lines: l.pop('_cached',None)
        cust=cmap.get(aser)
        if not cust: issues.append((sn,f'customer serial {aser} not in Name'))
        if not lines: issues.append((sn,'no lines'))
        if net==0: issues.append((sn,'zero total'))
        invoices.append({"no":re.sub(r'[\s\-]+$','',sn.strip()),"date":date,"customerSerial":aser,
            "customerName":cust['name'] if cust else None,"lines":lines,"subtotal":r2(sub),
            "discount":r2(dis),"summaryRows":adjustments,"total":r2(net),"proforma":proforma,"sheet":sn})
    except Exception as e:
        issues.append((sn,f'EXC {e!r}'))
json.dump({"customers":customers,"invoices":invoices},open(OUT,'w'),ensure_ascii=False,indent=1)
print("customers",len(customers),"invoices",len(invoices))
ds=sorted(i["date"] for i in invoices if i["date"]) or ["-"]; print("dates",ds[0],ds[-1])
print("sum totals",r2(sum(i['total'] for i in invoices)))
print("proforma",sum(i['proforma'] for i in invoices))
from collections import Counter
print("dup nos",[k for k,v in Counter(i['no'] for i in invoices).items() if v>1])
print("ISSUES"); [print(' ',x) for x in issues]
print("MISMATCH",len(mism)); [print(' ',x) for x in mism]
