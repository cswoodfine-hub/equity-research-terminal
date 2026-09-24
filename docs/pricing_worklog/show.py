import json, sys
for f in sys.argv[1:]:
    v = json.load(open(f))
    print("=====", v["ticker"], v["name"], "| refuse:", v.get("refuse"))
    def line(k, x, ind=""):
        if not isinstance(x, dict): return
        print(f"  {ind[:22]:22} {k:24} {str(x.get('value'))[:14]:14} {x.get('verdict','')[:9]:9} {(x.get('unit') or '')[:28]:28} | {(x.get('source') or '')[:120]}")
    for k, x in v["asset"].items(): line(k, x)
    for b in v.get("indications") or []:
        for k, x in b["fields"].items(): line(k, x, b["indication"])
