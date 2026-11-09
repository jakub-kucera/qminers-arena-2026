"""Fit causal experts and calibrate a nonnegative blend before policy validation."""
import json
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from sklearn.ensemble import GradientBoostingRegressor
from run_study import ROOT, OUT, dump, load_bot

DEST=ROOT/'research/composite_results'


def fit_linear(x,y,mask):
    mean=x[mask].mean(axis=0)
    scale=np.maximum(x[mask].std(axis=0),1e-9)
    z=(x[mask]-mean)/scale
    center=float(y[mask].mean())
    co=np.linalg.solve(z.T@z+100*np.eye(x.shape[1]),z.T@(y[mask]-center))/scale
    return co,center-float(mean@co)


def fit_experts(x,y1,y5,t,cut):
    m1=(t>=t[0]+10e6)&(t+1e6<cut)
    m5=(t>=t[0]+10e6)&(t+5e6<cut)
    c1,b1=fit_linear(x,y1,m1)
    c5,b5=fit_linear(x,y5,m5)
    tree=GradientBoostingRegressor(n_estimators=32,max_depth=2,learning_rate=.08,
        min_samples_leaf=200,loss='huber',random_state=42)
    tree.fit(x[m1],y1[m1])
    return c1,b1,c5,b5,tree


def predictions(models,x):
    c1,b1,c5,b5,tree=models
    return np.column_stack([x@c1+b1,x@c5+b5,tree.predict(x),x[:,8],np.zeros(len(x))])


def main():
    a=np.load(OUT/'record_trace.npz')['features']
    t=a[:,0];x=a[:,5:];mid=(a[:,1]+a[:,2])/2
    duration=t[-1]-t[0]
    cut40=t[0]+.4*duration;cut50=t[0]+.5*duration;cut75=t[0]+.75*duration
    y1=mid[np.searchsorted(t,t+1e6,side='right')-1]-mid
    y5=mid[np.searchsorted(t,t+5e6,side='right')-1]-mid
    initial=fit_experts(x,y1,y5,t,cut40)
    calibration=(t>=cut40)&(t+1e6<cut50)
    cal=predictions(initial,x[calibration]);target=y1[calibration]
    prior=np.array([.4,.1,.3,.1,.1])
    opt=minimize(lambda w:float(np.mean((cal@w-target)**2)+.001*np.sum((w-prior)**2)),
        prior,bounds=[(0,1)]*5,constraints={'type':'eq','fun':lambda w:float(w.sum()-1)},
        method='SLSQP',options={'ftol':1e-12,'maxiter':1000})
    assert opt.success,opt.message
    weights=opt.x
    models=fit_experts(x,y1,y5,t,cut50)
    c1,b1,c5,b5,tree=models
    trees=[]
    for estimator in tree.estimators_[:,0]:
        tr=estimator.tree_
        trees.append([[int(tr.feature[i]),float(tr.threshold[i]),int(tr.children_left[i]),
                       int(tr.children_right[i]),float(tr.value[i,0,0])] for i in range(tr.node_count)])
    params=dict(COEF1=c1.tolist(),INTERCEPT1=b1,COEF5=c5.tolist(),INTERCEPT5=b5,
        TREE_BASE=float(tree.init_.constant_[0,0]),TREE_RATE=tree.learning_rate,TREES=trees,WEIGHTS=weights.tolist())
    bot=load_bot(ROOT/'strategies/composite_template.py',dict(params,MODEL='ensemble'))
    sample=x[np.linspace(0,len(x)-1,1500).astype(int)]
    # sklearn tree splits convert input to float32, so verify practical export parity.
    expected=np.clip(predictions(models,sample)@weights,-2,2)
    actual=np.array([bot.predict(row.tolist()) for row in sample])
    maximum_error=float(np.max(np.abs(expected-actual)))
    assert maximum_error<1e-8,maximum_error
    valid=(t>=cut50)&(t+5e6<cut75)
    pred=predictions(models,x[valid])
    labels=['ridge_1s','ridge_5s','boosted_1s','microprice','zero','ensemble']
    pred=np.column_stack([pred,pred@weights])
    metrics={}
    for i,label in enumerate(labels):
        metrics[label]={'mse':float(np.mean((pred[:,i]-y1[valid])**2)),
            'correlation':float(np.corrcoef(pred[:,i],y1[valid])[0,1]) if np.std(pred[:,i]) else None,
            'abs_prediction_q95':float(np.quantile(np.abs(pred[:,i]),.95))}
    dump(DEST/'model_params.json',params)
    dump(DEST/'model_fit.json',dict(experts=labels[:-1],weights=weights.tolist(),
        initial_fit_end_s=cut40/1e6,blend_calibration_end_s=cut50/1e6,base_refit_end_s=cut50/1e6,
        policy_validation_end_s=cut75/1e6,validation_metrics=metrics,export_max_error=maximum_error,
        notes='Base fits use first 40%; blend weights use 40-50%; bases refit first 50%. Labels crossing boundaries are purged. No tail observations are used to choose weights.'))
    print(json.dumps({'weights':dict(zip(labels[:-1],weights.tolist())),'validation':metrics,'export_max_error':maximum_error},indent=2))


if __name__=='__main__':
    main()
