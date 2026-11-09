"""Does a wide spread predict the next move, and in which direction? (7 Nov, round 2.) A price-time replay of a tape (experiments.tape.tape_book), sampled every 100 ms: the mid's move 1 / 5 / 30 s on by the spread, and on a 3+ tick spread by which side moved over the last second.

    uv run python -m experiments.tape.wide_spread data/arena/round2/round2_public.csv
"""
import csv,sys,statistics
sys.path.insert(0,'python')
from experiments.tape.tape_book import Book
b=Book(); S=[]; nxt=0.0
with open(sys.argv[1]) as f:
    r=csv.reader(f); next(r)
    for row in r:
        t=float(row[0])
        while t>=nxt:
            S.append((b.best[0],b.best[1])); nxt+=0.1
        side=0 if row[3]=='B' else 1
        if row[1]=='Insert': b.insert(int(row[2]),side,int(row[5]),int(row[4]),row[6]=='F')
        else: b.cancel(int(row[2]))
mid=[(x+y)/2 if x is not None and y is not None else None for x,y in S]
# fill gaps
last=None
for i,m in enumerate(mid):
    if m is None: mid[i]=last
    else: last=m
def fut(i,k): return mid[min(i+k,len(mid)-1)]-mid[i]
rows=[]
for i in range(10,len(S)-300):
    bb,aa=S[i]; pb,pa=S[i-10]  # 1 s earlier
    if None in (bb,aa,pb,pa): continue
    sp=aa-bb; db=bb-pb; da=aa-pa
    rows.append((sp,db,da,fut(i,10),fut(i,50),fut(i,300)))
def summ(name,sel):
    if not sel: print(name,'n=0'); return
    print(f"{name:52s} n={len(sel):6d}  1s {statistics.mean(r[3] for r in sel):+.2f}  5s {statistics.mean(r[4] for r in sel):+.2f}  30s {statistics.mean(r[5] for r in sel):+.2f}  |1s| {statistics.mean(abs(r[3]) for r in sel):.2f}")
summ('all samples',rows)
for lo,hi in ((1,1),(2,2),(3,4),(5,9),(10,999)):
    summ(f'spread {lo}-{hi}',[r for r in rows if lo<=r[0]<=hi])
print('-- wide (3+): which side moved over the last 1 s (signed future move)')
summ('spread 3+, bid fell, ask held or fell less',[r for r in rows if r[0]>=3 and r[1]<0 and r[1]<r[2]])
summ('spread 3+, ask rose, bid held or rose less',[r for r in rows if r[0]>=3 and r[2]>0 and r[2]>r[1]])
summ('spread 3+, bid fell AND ask rose (both away)',[r for r in rows if r[0]>=3 and r[1]<0 and r[2]>0])
summ('spread 2, bid fell',[r for r in rows if r[0]==2 and r[1]<0 and r[1]<r[2]])
summ('spread 2, ask rose',[r for r in rows if r[0]==2 and r[2]>0 and r[2]>r[1]])
