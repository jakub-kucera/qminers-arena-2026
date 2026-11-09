"""Smooth neural residuals on a linear fair-value model; explicit training overlap."""
import json
from pathlib import Path
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.utils.parallel import _get_threadpool_controller
from scripts.round1_fixed_trees import collect
from simulator.main import load_strategy_from_file
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/neural_residual')


def export(model,scaler,beta,mode):
    text=Path('strategies/round1_private_554347.py').read_text().replace('isfinite\n','isfinite, log\n')
    text=text.replace('from simulator.models import','import numpy as np\n\nfrom simulator.models import')
    init='''        self._nn_mean=np.asarray('''+repr(scaler.mean_.tolist())+''',dtype=float)
        self._nn_scale=np.asarray('''+repr(scaler.scale_.tolist())+''',dtype=float)
        self._nn_w0=np.asarray('''+repr(model.coefs_[0].tolist())+''',dtype=float)
        self._nn_b0=np.asarray('''+repr(model.intercepts_[0].tolist())+''',dtype=float)
        self._nn_w1=np.asarray('''+repr(model.coefs_[1].tolist())+''',dtype=float)
        self._nn_b1=np.asarray('''+repr(model.intercepts_[1].tolist())+''',dtype=float)
        self._nn_beta='''+repr(tuple(float(v) for v in beta))+'''
'''
    text=text.replace('        self._orders = {}','        self._orders = {}\n'+init,1)
    helper='''    def _neural(self, features):
        x=(np.asarray(features,dtype=float)-self._nn_mean)/self._nn_scale
        hidden=np.tanh(x@self._nn_w0+self._nn_b0)
        return float((hidden@self._nn_w1+self._nn_b1)[0])

'''
    text=text.replace('    def _cancel(self, order_id):',helper+'    def _cancel(self, order_id):')
    addition='''        neural_features=features+(spread,(bn+an)/20,(bd_n+ad_n)/40,log(1+bq+aq)/10,
            (bq/max(1,bn)-aq/max(1,an))/max(1,bq/max(1,bn)+aq/max(1,an)))
'''
    if mode=='fixed':
        text=text.replace('        self._learn(now,mid)\n','')
        addition+='        prediction=sum(w*x for w,x in zip(self._nn_beta,features))+self._neural(neural_features)\n'
    else:
        addition+='        prediction+=self._neural(neural_features)\n'
    addition+='        prediction=max(-2.0,min(2.0,prediction))\n'
    return text.replace('        fair = mid + ',addition+'        fair = mid + ')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'full.json').exists():raise SystemExit('Results already exist')
    data=collect();specs={};search_queue.ROOT=ROOT
    for fraction in (0.6,1.0):
        mask=data['t']<12000000000*fraction;x=data['x'][mask];y=np.clip(data['y'][mask],-5,5)
        reflection=x.copy();reflection[:,list(range(15))+[19]]*=-1
        x=np.concatenate((x,reflection));y=np.concatenate((y,-y))
        beta=np.linalg.solve(x[:,:15].T@x[:,:15]+np.eye(15)*len(x)/1300,x[:,:15].T@y)
        residual=y-x[:,:15]@beta
        scaler=StandardScaler();xx=scaler.fit_transform(x)
        for alpha in (0.1,1.0):
            model=MLPRegressor(hidden_layer_sizes=(32,),activation='tanh',alpha=alpha,batch_size=1024,
                learning_rate_init=0.001,max_iter=40,early_stopping=True,n_iter_no_change=5,
                validation_fraction=0.1,tol=1e-6,random_state=1729)
            with _get_threadpool_controller().limit(limits=1):model.fit(xx,residual)
            for mode in ('fixed','hybrid'):
                name=f'nn_{fraction}_{alpha}_{mode}'
                path=ROOT/'sources'/(name+'.py');path.write_text(export(model,scaler,beta,mode))
                assert not check(path),check(path)
                s=load_strategy_from_file(path);test=x[::10000]
                assert np.max(np.abs(np.array([s._neural(tuple(row)) for row in test])-model.predict(scaler.transform(test))))<1e-10
                specs[name]=dict(training_fraction=fraction,alpha=alpha,mode=mode,iterations=model.n_iter_,
                    loss=float(model.loss_),in_sample=fraction==1.0,source_sha256=digest(path))
            print('FIT NEURAL',fraction,alpha,'iterations',model.n_iter_,'loss',model.loss_,flush=True)
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Fixed trained neural residual; stated training fraction overlaps full replay. No independent holdout.'),indent=2)+'\n')
    print('WINNER NEURAL',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
