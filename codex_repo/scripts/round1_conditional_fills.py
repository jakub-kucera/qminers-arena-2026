"""Learn conditional execution profitability from matured own-fill markouts."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/conditional_fills')


def source_for(horizon, threshold, mode):
    text=Path('strategies/round1_submission.py').read_text()
    text=text.replace('        self._orders = {}', '''        self._orders = {}
        self._fill_pending = deque(maxlen=4096)
        self._fill_features = None
        self._fill_mid = self._fill_spread = 0.0
        self._fill_xx = [[0.0]*18 for _ in range(18)]
        self._fill_xy = [0.0]*18
        self._fill_weights = [0.0]*18
        self._fill_mass = 0.0
        self._fill_labels = 0
        self._fill_last_label = self._fill_last_fit = None''',1)
    helper=f'''    def _fill_frame(self, sign, price, features, mid, spread):
        return (1.0,spread,sign*(mid-price))+tuple(sign*x for x in features)

    def _learn_fills(self, now, mid):
        while self._fill_pending and self._fill_pending[0][0]+{horizon} <= now:
            stamp,price,features,sign,weight = self._fill_pending.popleft()
            if now-stamp > {horizon}+1000000:
                continue
            dt = 0 if self._fill_last_label is None else now-self._fill_last_label
            self._fill_last_label = now
            decay = exp(-max(0,dt)/300000000)
            target = max(-20,min(20,sign*(mid-price)))
            self._fill_mass = self._fill_mass*decay+weight
            for i in range(18):
                self._fill_xy[i] = self._fill_xy[i]*decay+weight*features[i]*target
                for j in range(18):
                    self._fill_xx[i][j] = self._fill_xx[i][j]*decay+weight*features[i]*features[j]
            self._fill_labels += 1
        if self._fill_labels < 100:
            return
        if self._fill_last_fit is not None and now-self._fill_last_fit < 1000000:
            return
        self._fill_last_fit = now
        matrix = [self._fill_xx[i][:]+[self._fill_xy[i]] for i in range(18)]
        ridge = max(10.0,0.001*self._fill_mass)
        for i in range(18):
            matrix[i][i] += ridge
        for col in range(18):
            pivot = matrix[col][col]
            if not isfinite(pivot) or pivot <= 1e-12:
                return
            for j in range(col,19):
                matrix[col][j] /= pivot
            for i in range(18):
                if i == col:
                    continue
                factor = matrix[i][col]
                for j in range(col,19):
                    matrix[i][j] -= factor*matrix[col][j]
        weights = [matrix[i][18] for i in range(18)]
        if all(isfinite(w) for w in weights):
            self._fill_weights = weights

    def _fill_edge(self, sign, price, features, mid, spread):
        frame = self._fill_frame(sign,price,features,mid,spread)
        return sum(w*x for w,x in zip(self._fill_weights,frame))

'''
    text=text.replace('    def _cancel(self, order_id):',helper+'    def _cancel(self, order_id):')
    text=text.replace('self._orders[order_id] = [sign,price,quantity,False,False,now]', '''frame = None if self._fill_features is None else self._fill_frame(sign,price,
            self._fill_features,self._fill_mid,self._fill_spread)
        self._orders[order_id] = [sign,price,quantity,False,False,now,frame]''')
    text=text.replace('        self._learn(now,mid)', '''        self._learn(now,mid)
        self._learn_fills(now,mid)
        self._fill_features,self._fill_mid,self._fill_spread = features,mid,spread''')
    decision=f'''        if self._fill_labels >= 100:
            inventory_bias = 0.1*self.inventory/100
'''
    if mode=='gate':
        decision+=f'''            if self._fill_edge(1,buy,features,mid,spread) < {threshold}+inventory_bias:
                buy = min(buy,bid-1)
            if self._fill_edge(-1,sell,features,mid,spread) < {threshold}-inventory_bias:
                sell = max(sell,ask+1)
'''
    else:
        decision+=f'''            buy = bid if self._fill_edge(1,bid,features,mid,spread) >= {threshold}+inventory_bias else bid-1
            sell = ask if self._fill_edge(-1,ask,features,mid,spread) >= {threshold}-inventory_bias else ask+1
            if spread >= 2:
                if self._fill_edge(1,bid+1,features,mid,spread) >= {threshold}+inventory_bias+0.1:
                    buy = min(ask-1,bid+1)
                elif self._fill_edge(-1,ask-1,features,mid,spread) >= {threshold}-inventory_bias+0.1:
                    sell = max(bid+1,ask-1)
'''
    text=text.replace('        # Withdraw the side',decision+'        # Withdraw the side')
    text=text.replace('''        elif event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self.inventory''','''        elif event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            if record[6] is not None and event.filled_quantity > 0:
                self._fill_pending.append((event.timestamp_us,event.fill_price,record[6],record[0],min(20,event.filled_quantity)))
            self.inventory''')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    for horizon in (100000,500000):
        for threshold in (-0.1,0.0,0.1):
            for mode in ('gate','replace'):
                name=f'fills_{horizon}_{threshold}_{mode}'
                path=ROOT/'sources'/(name+'.py');path.write_text(source_for(horizon,threshold,mode))
                assert not check(path),check(path)
                specs[name]=dict(horizon_us=horizon,threshold=threshold,mode=mode,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning; own fill labels are learned only after their markout horizon matures.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
