"""Development diagnostic: slower trend versus reversion with real IOC costs."""
from pathlib import Path
from scripts.round2_structural_batch import run


def build():
    base = Path('strategies/round2/round2_guarded_trend.py').read_text()
    base = base.replace('POSITION_LIMIT = 80', 'POSITION_LIMIT = 100')
    base = base.replace('MAX_ORDER_SIZE = 20', 'MAX_ORDER_SIZE = 100')
    base = base.replace('self._guard_scale = 0.25', 'self._guard_scale = 1.0')
    begin = base.index('        self._guard_update(now, mid, spread)')
    end = base.index('    def on_private_order_update', begin)
    cases = {}
    for fast,slow in ((1,10),(5,30)):
        for sign,label in ((1,'trend'),(-1,'reversion')):
            policy = f'''        # Causal EMA displacement in ticks. Fixed hypotheses, no fitted path.
        signal = {sign} * (self._fast_mid-self._slow_mid)
        if abs(signal) > max(1.0, spread) and spread <= 2:
            target = self.POSITION_LIMIT if signal > 0 else -self.POSITION_LIMIT
        elif self.inventory * signal > 0 and abs(signal) > 0.25:
            target = self.inventory
        else:
            target = 0
        self._target = target
        self._send_toward(now,target,bid,ask,bid_quantity,ask_quantity)

'''
            text = base[:begin]+policy+base[end:]
            text = text.replace('elapsed / 500_000', f'elapsed / {fast*1000000}')
            text = text.replace('elapsed / 2_000_000', f'elapsed / {slow*1000000}')
            cases[f'{label}_{fast}s_{slow}s'] = text
    return cases


if __name__ == '__main__':
    run(Path('logs/round2_drift_batch'),build(),[
        'Persistent slower price drift versus reversion, using identical execution',
        'Strict 100-lot exposure; full spread crossing and actual native latency',
        'No virtual-edge guard or parameter fitting; four predeclared causal EMA rules'])
