"""Research metrics. Multiclass Brier uses the /2 convention throughout CORE."""
from math import log
from .contracts import number, integer


def probability_vector(p):
    if len(p)!=3: raise ValueError('three probabilities required')
    p=[number(x,'probability',0,1) for x in p]
    if abs(sum(p)-1)>1e-8: raise ValueError('probabilities must sum to one')
    return p


def log_loss(p,y):
    p=probability_vector(p);integer(y,'outcome',0,2)
    # The clipping convention is explicit in every report; it avoids JSON Infinity.
    return -log(max(1e-15,p[y]))


def metrics(predictions, outcomes, bins=10):
    integer(bins,'bins',1,100)
    if len(predictions)!=len(outcomes) or not outcomes: raise ValueError('nonempty paired observations required')
    ps=[probability_vector(p) for p in predictions]
    for y in outcomes: integer(y,'outcome',0,2)
    n=len(ps);classes=[]
    for c in range(3):
        reliability=[]
        for b in range(bins):
            indices=[i for i,p in enumerate(ps) if min(bins-1,int(p[c]*bins))==b]
            if not indices:continue
            forecast=sum(ps[i][c] for i in indices)/len(indices)
            frequency=sum(outcomes[i]==c for i in indices)/len(indices)
            reliability.append({'bin':b,'n':len(indices),'forecast':forecast,'frequency':frequency})
        classes.append({'class':c,'n':n,'brier':sum((p[c]-int(y==c))**2 for p,y in zip(ps,outcomes))/n,
                        'ece':sum(r['n']*abs(r['forecast']-r['frequency']) for r in reliability)/n,'reliability':reliability})
    confidence_bins=[]
    for b in range(bins):
        ids=[i for i,p in enumerate(ps) if min(bins-1,int(max(p)*bins))==b]
        if ids:confidence_bins.append({'bin':b,'n':len(ids),'confidence':sum(max(ps[i]) for i in ids)/len(ids),
            'accuracy':sum(max(range(3),key=lambda c:ps[i][c])==outcomes[i] for i in ids)/len(ids)})
    return {'n':n,'brier':sum(c['brier'] for c in classes)/2,'log_loss':sum(log_loss(p,y) for p,y in zip(ps,outcomes))/n,
            'log_loss_clip':1e-15,'ece_macro':sum(c['ece'] for c in classes)/3,'classwise':classes,
            'sharpness_mean_max':sum(max(p) for p in ps)/n,'entropy':-sum(sum(x*log(x) for x in p if x) for p in ps)/n,
            'confidence_bins':confidence_bins,'interval_coverage':None,
            'interval_note':'Individual true probabilities are unobserved; Bernoulli outcomes do not measure probability-interval coverage.'}


def devig(odds,method='proportional'):
    if len(odds)!=3:raise ValueError('complete 1X2 prices required')
    q=[1/number(o,'odds',1.00000001) for o in odds]
    if method=='proportional':return [x/sum(q) for x in q]
    if method=='shin':
        from math import sqrt
        total=sum(q)
        if total<1-1e-12: raise ValueError('Shin underround unsupported')
        if abs(total-1)<=1e-12:return [x/total for x in q]
        def probabilities(z):
            return [2*x*x/total/(sqrt(z*z+4*(1-z)*x*x/total)+z) for x in q]
        lo,hi=0.,1.
        for _ in range(200):
            mid=(lo+hi)/2;p=probabilities(mid);residual=sum(p)-1
            if abs(residual)<=1e-12:return p
            if residual>0:lo=mid
            else:hi=mid
        raise ValueError('Shin failed to converge')
    if method!='power':raise ValueError('supported methods: proportional, power, shin')
    lo,hi=0.,1.
    while sum(x**hi for x in q)>1:hi*=2
    for _ in range(80):
        mid=(lo+hi)/2
        if sum(x**mid for x in q)>1:lo=mid
        else:hi=mid
    p=[x**((lo+hi)/2) for x in q]
    return [x/sum(p) for x in p]


def market_consensus(books,method='proportional'):
    """Caller must supply contemporaneous, same-market executable quotes."""
    if not books or len({b['bookmaker'] for b in books})!=len(books):raise ValueError('unique bookmakers required')
    ps=[devig(b['odds'],method) for b in books]
    return {'method':method,'n':len(books),'fair_probability':[sum(p[i] for p in ps)/len(ps) for i in range(3)],
            'dispersion':[max(p[i] for p in ps)-min(p[i] for p in ps) for i in range(3)],
            'best':[{'bookmaker':max(books,key=lambda b:b['odds'][i])['bookmaker'],'odds':max(b['odds'][i] for b in books)} for i in range(3)]}
