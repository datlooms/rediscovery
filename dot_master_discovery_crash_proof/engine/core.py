import pandas as pd, numpy as np
from numba import njit
import warnings; warnings.filterwarnings('ignore')

ERP=50; POINT=0.01; ANCHOR=18*3600
TARGETS=['KAMA_Value','KAMA_Slope','KAMA_Dist','KAMA_Dist_ATR','KAMA_Side',
         'HarmVol_EMA8','HarmVol_EMA21','EMA_Oscillator','Harmonic_LLEMA','Harmonic_Sign',
         'Harmonic_OBVf_Concordance','Harmonic_D2D_Concordance','PoC_Price','Dist_To_PoC_ATR','PoC_Side',
         'ADX_Value']

def load(parts,base='/mnt/project/'):
    d0=pd.read_csv(base+parts[0]); cols=list(d0.columns)
    dfs=[d0]+[pd.read_csv(base+p,header=None,names=cols) for p in parts[1:]]
    df=pd.concat(dfs,ignore_index=True)
    df['_dt']=pd.to_datetime(df['Time'],format='%Y.%m.%d %H:%M')
    df['_unix']=((df['_dt']-pd.Timestamp('1970-01-01')).dt.total_seconds().astype(np.int64))
    df['_bucket']=df['_unix']//86400
    return df,cols

def capped_poc(H,L,C,V,bucket):
    n=len(C); poc=np.empty(n)
    starts=np.where(np.diff(bucket,prepend=bucket[0]-1)!=0)[0]
    for di in range(len(starts)):
        s=starts[di]; e=starts[di+1]-1 if di+1<len(starts) else n-1
        for t in range(s,e+1):
            mp=L[s:t+1].min(); xp=H[s:t+1].max(); rng=xp-mp
            if rng<=0: poc[t]=C[t]; continue
            nb=int(rng/POINT)+1
            if nb>5000: nb=5000
            idx=((C[s:t+1]-mp)/POINT).astype(np.int64)
            m=(idx>=0)&(idx<nb)
            if m.any():
                b=np.bincount(idx[m],weights=V[s:t+1][m],minlength=nb)
                mi=int(np.argmax(b))
            else: mi=0
            poc[t]=mp+mi*POINT
    return poc

ADX_PERIOD=14
@njit
def adx_wilder(H,L,C,period,point):
    n=len(C); adx=np.zeros(n)
    sPDM=0.0; sMDM=0.0; sTR=0.0; prev_adx=0.0; alpha=1.0/period
    for t in range(2,n):
        hi=H[t]; lo=L[t]; prev_hi=H[t-1]; prev_lo=L[t-1]; prev_cl=C[t-1]
        up=hi-prev_hi; dn=prev_lo-lo
        plusDM=up if (up>dn and up>0) else 0.0
        minusDM=dn if (dn>up and dn>0) else 0.0
        tr=hi-lo
        a2=abs(hi-prev_cl); a3=abs(lo-prev_cl)
        if a2>tr: tr=a2
        if a3>tr: tr=a3
        if tr==0.0: tr=point
        sPDM=sPDM*(1.0-alpha)+plusDM*alpha
        sMDM=sMDM*(1.0-alpha)+minusDM*alpha
        sTR=sTR*(1.0-alpha)+tr*alpha
        diPlus=(sPDM/sTR)*100.0 if sTR>0 else 0.0
        diMinus=(sMDM/sTR)*100.0 if sTR>0 else 0.0
        ssum=diPlus+diMinus
        dx=(abs(diPlus-diMinus)/ssum)*100.0 if ssum!=0 else 0.0
        prev_adx=prev_adx*(1.0-alpha)+dx*alpha
        adx[t]=prev_adx
    return adx

def families(df):
    c=df['Close'].values.astype(float); n=len(c)
    ema8=pd.Series(c).ewm(alpha=2/9,adjust=False).mean().values
    ema21=pd.Series(c).ewm(alpha=2/22,adjust=False).mean().values
    emaosc=ema8-ema21
    d2d=df['D2D_Basis'].values.astype(float); atra=df['ATR_Assigned'].values.astype(float); atr1m=df['ATR_1M'].values.astype(float)
    dcl=np.abs(np.diff(c,prepend=c[0]))
    volat=pd.Series(dcl).rolling(ERP).sum().values
    direction=np.abs(c-pd.Series(c).shift(ERP).values)
    er=np.nan_to_num(np.where((volat>0)&~np.isnan(volat),direction/volat,0.0))
    fastSC=2/3; slowSC=2/31; sc=(er*(fastSC-slowSC)+slowSC)**2
    kama=np.zeros(n); SEED=ERP-1
    if n>SEED:
        kama[SEED]=d2d[SEED] if d2d[SEED]>0 else c[SEED]
        for t in range(SEED+1,n): kama[t]=kama[t-1]+sc[t]*(c[t]-kama[t-1])
    kprev=np.concatenate([[kama[0]],kama[:-1]])
    kslope=kama-kprev; kdist=c-kama
    kdistatr=np.where(atr1m>0,kdist/atr1m,0.0)
    kside=np.where(c>kama,1,np.where(c<kama,-1,0)).astype(int)
    raw=kama-kprev; dz=np.where(atr1m>0,atr1m/30.0,0.0)
    llema=np.where(np.abs(raw)<=dz,0.0,raw); llema[:SEED+1]=0.0
    hsign=np.where(llema>0,1,np.where(llema<0,-1,0)).astype(int)
    obvf=df['OBVf_Signal'].values.astype(int); d2dd=df['D2D_Trend_Dir'].values.astype(int)
    hobvf=np.where((hsign!=0)&(hsign==obvf),1,0).astype(int)
    hd2d=np.where((hsign!=0)&(hsign==d2dd),1,0).astype(int)
    H=df['High'].values.astype(float); L=df['Low'].values.astype(float)
    adxval=adx_wilder(H,L,c,ADX_PERIOD,POINT)
    hv=df['Hist_Volume'].values.astype(float); vv=df['Volume'].values.astype(float)
    vol=np.where((hv<=0)&(vv>0),vv,hv).astype(np.int64)
    poc=capped_poc(H,L,c,vol,df['_bucket'].values)
    distpoc=np.where((atr1m>0)&(poc>0),np.abs(c-poc)/atr1m,0.0)
    pside=np.where(poc>0,np.where(c>poc,1,np.where(c<poc,-1,0)),0).astype(int)
    return {'KAMA_Value':kama,'KAMA_Slope':kslope,'KAMA_Dist':kdist,'KAMA_Dist_ATR':kdistatr,'KAMA_Side':kside,
            'HarmVol_EMA8':ema8,'HarmVol_EMA21':ema21,'EMA_Oscillator':emaosc,'Harmonic_LLEMA':llema,'Harmonic_Sign':hsign,
            'Harmonic_OBVf_Concordance':hobvf,'Harmonic_D2D_Concordance':hd2d,
            'PoC_Price':poc,'Dist_To_PoC_ATR':distpoc,'PoC_Side':pside,
            'ADX_Value':adxval}

def _is_dst(dt):
    yr=dt.dt.year
    def first_sun(month):
        d=pd.to_datetime(dict(year=yr,month=month,day=1)); wd=(d.dt.dayofweek+1)%7; return 1+((7-wd)%7)
    ss=first_sun(3)+7; fsn=first_sun(11)
    start=pd.to_datetime(dict(year=yr,month=3,day=ss,hour=2)); end=pd.to_datetime(dict(year=yr,month=11,day=fsn,hour=2))
    return ((dt>=start)&(dt<end)).values

@njit
def va_all(H,L,C,V,starts):
    n=len(C); poc=np.empty(n); VAH=np.empty(n); VAL=np.empty(n)
    for r in range(n):
        ds=starts[r]; minP=L[ds]; maxP=H[ds]
        for k in range(ds,r+1):
            if L[k]<minP: minP=L[k]
            if H[k]>maxP: maxP=H[k]
        rng=maxP-minP
        if rng<=0:
            poc[r]=C[r]; VAH[r]=C[r]; VAL[r]=C[r]; continue
        nb=int(rng/POINT)+1
        if nb>5000: nb=5000
        bins=np.zeros(nb,dtype=np.int64)
        for k in range(ds,r+1):
            idx=int((C[k]-minP)/POINT)
            if 0<=idx<nb: bins[idx]+=V[k]
        mx=0; mxv=bins[0]
        for b in range(1,nb):
            if bins[b]>mxv: mxv=bins[b]; mx=b
        poc[r]=minP+mx*POINT
        tot=0
        for b in range(nb): tot+=bins[b]
        tgt=tot*0.70; acc=bins[mx]; vah=mx; val=mx
        while acc<tgt and (val>0 or vah<nb-1):
            vu=bins[vah+1] if vah+1<nb else -1
            vd=bins[val-1] if val-1>=0 else -1
            if vu>vd: acc+=vu; vah+=1
            elif vd!=-1: acc+=vd; val-=1
            elif vu!=-1: acc+=vu; vah+=1
            else: break
        VAH[r]=minP+vah*POINT; VAL[r]=minP+val*POINT
    return poc,VAH,VAL

def compute_new45(df,atr):
    n=len(df)
    C=df['Close'].values.astype(float); O=df['Open'].values.astype(float)
    H=df['High'].values.astype(float); L=df['Low'].values.astype(float)
    V=df['Volume'].values.astype(float)
    ep=df['_unix'].values; srv=df['_bucket'].values
    off=np.where(_is_dst(df['_dt']),-4*3600,-5*3600); est_ep=ep+off
    est_day=(est_ep-ANCHOR)//86400; est_week=(est_ep-259200-ANCHOR)//604800
    g=pd.DataFrame({'srv':srv,'eday':est_day,'ewk':est_week,'O':O,'H':H,'L':L,'C':C,'V':V})
    pv=C*V; ppv=C*C*V
    cumV=pd.Series(V).groupby(srv).cumsum().values
    cumPV=pd.Series(pv).groupby(srv).cumsum().values; cumPPV=pd.Series(ppv).groupby(srv).cumsum().values
    vwap=np.where(cumV>0,cumPV/np.where(cumV>0,cumV,1),C)
    var=np.where(cumV>0,cumPPV/np.where(cumV>0,cumV,1)-vwap*vwap,0.0); var=np.where(var<0,0,var); sigma=np.sqrt(var)
    starts=np.zeros(n,dtype=np.int64); cur=0
    for r in range(n):
        if r>0 and srv[r]!=srv[r-1]: cur=r
        starts[r]=cur
    Vint=df['Volume'].values.astype(np.int64)
    POC,VAH,VAL=va_all(H,L,C,Vint,starts)
    DailyOpen=g.groupby('eday')['O'].transform('first').values
    SessH=g.groupby('eday')['H'].cummax().values; SessL=g.groupby('eday')['L'].cummin().values
    mod=df['EST_Hour'].values*60+df['EST_Minute'].values; orm=(mod>=570)&(mod<630)
    ORh=pd.Series(np.where(orm,H,-np.inf)).groupby(est_day).cummax().values
    ORl=pd.Series(np.where(orm,L,np.inf)).groupby(est_day).cummin().values
    ORh=np.where(np.isfinite(ORh),ORh,0.0); ORl=np.where(np.isfinite(ORl),ORl,0.0)
    dH=g.groupby('eday')['H'].max(); dL=g.groupby('eday')['L'].min(); dC=g.groupby('eday')['C'].last()
    pdH=np.nan_to_num(dH.shift(1).reindex(est_day).values)
    pdL=np.nan_to_num(dL.shift(1).reindex(est_day).values)
    pdC=np.nan_to_num(dC.shift(1).reindex(est_day).values)
    WeeklyOpen=g.groupby('ewk')['O'].transform('first').values
    W=2760
    S0=pd.Series(C).rolling(W).sum().values; ia=np.arange(n,dtype=float)
    S1=pd.Series(ia*C).rolling(W).sum().values; st=ia-W+1
    Spy=S1-st*S0; Sp=W*(W-1)/2.0; Spp=(W-1)*W*(2*W-1)/6.0; den=W*Spp-Sp*Sp
    slope=(W*Spy-Sp*S0)/den; md_slope=np.where(atr>0,slope/np.where(atr>0,atr,1),0.0)
    md_slope[:W-1]=0.0
    hh=pd.Series(H).rolling(W).max().values; ll=pd.Series(L).rolling(W).min().values
    md_pos=np.where(hh>ll,(C-ll)/np.where(hh>ll,hh-ll,1),0.5); md_pos[:W-1]=0.5
    def dist(Lv): return np.where((atr>0)&(Lv>0),np.abs(C-Lv)/np.where(atr>0,atr,1),0.0)
    def side(Lv): return np.where(Lv>0,np.sign(C-Lv),0).astype(int)
    def rnd(Nn): return np.where(atr>0,np.abs(C-np.floor(C/Nn+0.5)*Nn)/np.where(atr>0,atr,1),0.0)
    return {
        'VWAP_Price':vwap,'VWAP_Sigma':sigma,'VWAP_Dist_ATR':dist(vwap),'VWAP_Side':side(vwap),
        'VWAP_Z':np.where((sigma>0)&(vwap>0),(C-vwap)/np.where(sigma>0,sigma,1),0.0),
        'VAH_Price':VAH,'VAH_Dist_ATR':dist(VAH),'VAH_Side':side(VAH),
        'VAL_Price':VAL,'VAL_Dist_ATR':dist(VAL),'VAL_Side':side(VAL),
        'VA_Position':np.where((VAH>0)&(VAL>0)&(VAH>VAL),(C-VAL)/np.where(VAH>VAL,VAH-VAL,1),0.5),
        'PrevDay_High':pdH,'PrevDay_High_Dist_ATR':dist(pdH),'PrevDay_High_Side':side(pdH),
        'PrevDay_Low':pdL,'PrevDay_Low_Dist_ATR':dist(pdL),'PrevDay_Low_Side':side(pdL),
        'PrevDay_Close':pdC,'PrevDay_Close_Dist_ATR':dist(pdC),'PrevDay_Close_Side':side(pdC),
        'DailyOpen_Price':DailyOpen,'DailyOpen_Dist_ATR':dist(DailyOpen),'DailyOpen_Side':side(DailyOpen),
        'Round_100_Dist_ATR':rnd(100),'Round_500_Dist_ATR':rnd(500),'Round_1000_Dist_ATR':rnd(1000),
        'OR_High':ORh,'OR_High_Dist_ATR':dist(ORh),'OR_High_Side':side(ORh),
        'OR_Low':ORl,'OR_Low_Dist_ATR':dist(ORl),'OR_Low_Side':side(ORl),
        'OR_Position':np.where((ORh>0)&(ORl>0)&(ORh>ORl),(C-ORl)/np.where(ORh>ORl,ORh-ORl,1),0.5),
        'Session_High':SessH,'Session_High_Dist_ATR':dist(SessH),'Session_High_Side':side(SessH),
        'Session_Low':SessL,'Session_Low_Dist_ATR':dist(SessL),'Session_Low_Side':side(SessL),
        'WeeklyOpen_Price':WeeklyOpen,'WeeklyOpen_Dist_ATR':dist(WeeklyOpen),'WeeklyOpen_Side':side(WeeklyOpen),
        'MultiDay_Slope':md_slope,'MultiDay_Position':md_pos,
    }

print("Loading...")
old,cols=load(['first.csv','second.csv','third.csv','fourth.csv'])
new,cols256=load(['64_256_first.csv','64_256_second.csv','64_256_third.csv','64_256_fourth.csv'])
cols171=cols256[:171]
NEW45=cols171[126:]
print(f"old {len(old)} cols={len(cols)}   new {len(new)} cols={len(cols171)}   new45={len(NEW45)}")
assert cols171[:126]==cols, "126-col schema mismatch between original and 64_256"

print("\n=== GATE 1 (15-family Calc vs 64_256) ===")
fn=families(new)
print(f"{'column':28s}{'max_all':>13s}{'max_skip60':>13s}")
for col in TARGETS:
    r=np.abs(new[col].values.astype(float)-fn[col].astype(float))
    print(f"{col:28s}{np.nanmax(r):>13.6f}{np.nanmax(r[60:]):>13.6f}")

print("\n=== overlap: OHLCV identity + delta detection ===")
ovT=set(old['Time'])&set(new['Time'])
mo=old[old['Time'].isin(ovT)].sort_values('Time').reset_index(drop=True)
mn=new[new['Time'].isin(ovT)].sort_values('Time').reset_index(drop=True)
print(f"overlap rows {len(mo)}  ({mo['Time'].iloc[0]} -> {mo['Time'].iloc[-1]})")
for col in ['Open','High','Low','Close']:
    print(f"  {col} max|diff|={np.abs(mo[col].values-mn[col].values).max():.8f}")
print(f"  Volume max|diff|={int(np.abs(mo['Volume'].values-mn['Volume'].values).max())}")

RAW0={'Open','High','Low','Close','Volume','EST_Hour','EST_Minute','EST_DayOfWeek','Bar_Range','Body_Size','Upper_Wick','Lower_Wick'}
cons=-2
numcols=[c for c in cols if c!='Time' and pd.api.types.is_numeric_dtype(old[c]) and c not in TARGETS]
shiftmap={}
for col in numcols:
    o=mo[col].astype(float); nw=mn[col].astype(float).values
    r0=np.nanmedian(np.abs(o.values-nw)); r2=np.nanmedian(np.abs(o.shift(cons).values-nw))
    if col in RAW0: shiftmap[col]=0
    elif r0<r2-1e-9: shiftmap[col]=0
    else: shiftmap[col]=cons
from collections import Counter
print("  shift distribution:",dict(Counter(shiftmap.values())),f"(kept0={sum(s==0 for s in shiftmap.values())} shifted={sum(s!=0 for s in shiftmap.values())})")

print("\n=== correcting OLD: delta-shift + recompute 15 families ===")
oc=old.copy()
for col,s in shiftmap.items():
    if s!=0: oc[col]=oc[col].shift(s)
if 'Lock_Time' in cols: oc['Lock_Time']=oc['Lock_Time'].shift(cons)
fo=families(oc)
for col in TARGETS: oc[col]=fo[col]

print("\n=== computing 45 new columns for corrected OLD ===")
atr_old=oc['ATR_1M'].values.astype(float)
n45=compute_new45(oc,atr_old)
for col in NEW45: oc[col]=n45[col]
print(f"  added {len(NEW45)} columns -> oc now {oc.shape[1]} cols (+helpers)")

print("\n=== GATE 2 (corrected OLD 15-families vs 64_256, overlap >= 2026.04.10) ===")
g2T=sorted(t for t in ovT if t>='2026.04.10')
ocg=oc[oc['Time'].isin(g2T)].sort_values('Time').reset_index(drop=True)
nng=new[new['Time'].isin(g2T)].sort_values('Time').reset_index(drop=True)
print(f"gate2 rows {len(ocg)}")
print(f"{'column':28s}{'max':>13s}{'median':>13s}")
for col in TARGETS:
    r=np.abs(ocg[col].values.astype(float)-nng[col].values.astype(float))
    print(f"{col:28s}{np.nanmax(r):>13.6f}{np.nanmedian(r):>13.6f}")

print("\n=== GATE 3 (corrected OLD 45-new vs 64_256, overlap >= 2026.04.13, deep-lookback warm) ===")
g3T=sorted(t for t in ovT if t>='2026.04.13')
ocg3=oc[oc['Time'].isin(g3T)].sort_values('Time').reset_index(drop=True)
nng3=new[new['Time'].isin(g3T)].sort_values('Time').reset_index(drop=True)
print(f"gate3 rows {len(ocg3)}")
print(f"{'column':28s}{'exact%':>9s}{'meanAbs':>12s}{'maxAbs':>12s}")
for col in NEW45:
    a=ocg3[col].values.astype(float); b=nng3[col].values.astype(float)
    if col.endswith('_Side'):
        ex=(a==b).mean()*100
    else:
        prec=2 if col.endswith('_Price') else 6
        ex=(np.round(a,prec)==np.round(b,prec)).mean()*100
    print(f"{col:28s}{ex:8.2f}%{np.abs(a-b).mean():12.2e}{np.abs(a-b).max():12.2e}")

print("\n=== STITCH (171-wide) ===")
seam='2026.04.13 01:05'
oldpart=oc[oc['Time']<seam].copy()
newpart=new[new['Time']>=seam].copy()
out=pd.concat([oldpart,newpart],ignore_index=True)[cols171]
intcols=[c for c in cols171 if pd.api.types.is_integer_dtype(new[c])]
assert out[intcols].isna().sum().sum()==0,"NaN in integer columns before cast"
for c in intcols: out[c]=out[c].astype('int64')
t=pd.to_datetime(out['Time'],format='%Y.%m.%d %H:%M')
print(f"seam={seam}  old<seam={len(oldpart)}  new>=seam={len(newpart)}  total={len(out)}")
print(f"rows={len(out)} cols={len(out.columns)} range {out['Time'].iloc[0]} -> {out['Time'].iloc[-1]}")
print(f"strictly increasing={t.is_monotonic_increasing}  dups={int(out['Time'].duplicated().sum())}  NaN={int(out.isna().sum().sum())}")
print(f"cols order identical to 64_256={list(out.columns)==cols171}")
out.to_csv('/home/claude/equiDOT_reconstructed_171_step7.csv',index=False)
print("\nWROTE /home/claude/equiDOT_reconstructed_171_step7.csv")
