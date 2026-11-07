"""Touch imbalance and slow drift on a qminers tape (7 Nov): an aggregate-book replay of the CSV printing the next mid move and the move after 1 s by touch imbalance (bid - ask) / (bid + ask), and the corr of past and future mid moves over 60, 300, 600 s. Usage: uv run python -m experiments.day.touch_imbalance DATA.csv"""
import csv, sys
import numpy as np
P=sys.argv[1]
bids={};asks={};where={}
T=[];M=[];I=[]
for r in csv.reader(open(P)):
    if r[0]=='Time':continue
    t=float(r[0])
    if r[1]=='Cancel':
        oid=r[2]
        if oid in where:
            s,p,v=where.pop(oid); b=bids if s=='B' else asks
            if p in b:
                b[p]-=v
                if b[p]<=0: del b[p]
    else:
        oid,s,v,p,life=r[2],r[3],int(r[4]),int(r[5]),r[6]
        opp=asks if s=='B' else bids
        while v>0 and opp:
            bp=min(opp) if s=='B' else max(opp)
            if (s=='B' and bp>p) or (s=='A' and bp<p): break
            q=min(v,opp[bp]); opp[bp]-=q; v-=q
            if opp[bp]<=0: del opp[bp]
        if v>0 and life=='G':
            b=bids if s=='B' else asks
            b[p]=b.get(p,0)+v; where[oid]=(s,p,v)
    if bids and asks:
        bb=max(bids);ba=min(asks)
        T.append(t);M.append((bb+ba)/2);I.append((bids[bb]-asks[ba])/(bids[bb]+asks[ba]))
T=np.array(T);M=np.array(M);I=np.array(I)
chg=np.nonzero(np.diff(M))[0]+1
nxt=np.searchsorted(chg,np.arange(len(M)),side='right')
ok=nxt<len(chg)
d=np.where(ok,M[chg[np.minimum(nxt,len(chg)-1)]]-M,0)
B=[(-1,-.6),(-.6,-.2),(-.2,.2),(.2,.6),(.6,1.01)]
for lo,hi in B:
    m=ok&(I>=lo)&(I<hi); print('imb',lo,hi,m.sum(),'P(up)',(d[m]>0).mean().round(3),'mean next',d[m].mean().round(3))
j=np.searchsorted(T,T+1.0);okk=j<len(T);d1=M[np.minimum(j,len(T)-1)]-M
print('corr imb vs 1s',np.corrcoef(I[okk],d1[okk])[0,1])
for lo,hi in B:
    m=okk&(I>=lo)&(I<hi); print('1s',lo,hi,d1[m].mean().round(3))
g=np.arange(0,T[-1],1.0);mg=M[np.minimum(np.searchsorted(T,g),len(T)-1)]
for H in [60,300,600]:
    past=mg[H:]-mg[:-H]; fut=mg[2*H:]-mg[H:-H]
    print('drift H',H,'corr past vs future',np.corrcoef(past[:len(fut)],fut)[0,1].round(3))
