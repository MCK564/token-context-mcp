import json,sys,os
IGN={"latency_ms","latencies_ms","elapsed_ms","timestamp","index_run_id"}
def rd(p): return {(x.get("id")):x for x in (json.loads(l) for l in open(p) if l.strip())}
def cmp(a,b,name,arms=("R0-grep","R0-grep@R2","R0-read","R1","R2","R3"),verbose=True):
    tot=0
    for arm in arms:
        fa=f"{a}/bench_{name}_{arm}.jsonl"; fb=f"{b}/bench_{name}_{arm}.jsonl"
        if not (os.path.exists(fa) and os.path.exists(fb)): continue
        A,B=rd(fa),rd(fb); d={}
        for t in A:
            for k in A[t]:
                if k in IGN: continue
                if A[t][k]!=B.get(t,{}).get(k): d.setdefault(t,[]).append(k)
        tot+=len(d)
        if verbose or d: print(f"  {arm:11} differing tasks: {len(d)} {sorted(d)[:12]} fields={sorted({k for v in d.values() for k in v})[:8]}")
    return tot
if __name__=="__main__":
    a,b,name=sys.argv[1:4]; print(a,"vs",b); n=cmp(a,b,name); print("TOTAL differing task-arm records:",n)
