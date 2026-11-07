"""Align causal training loss with narrow-spread forecast execution."""
from pathlib import Path
from scripts.round2_t2_structural import SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    p=Path('strategies/round2/round2_local_294098.py')
    assert digest(p)=='06acfa3b209a6a3ccbf7beb08ec0715774c87bf98becdeae07f52465c3380f09'
    base=p.read_text()
    pairs=[('observed_us, old_mid, features = self._observations.popleft()',
            'observed_us, old_mid, features, sample_weight = self._observations.popleft()'),
           ('            elapsed = 0 if self._last_label_us is None else now - self._last_label_us',
            '            if sample_weight<=0:\n                continue\n            elapsed = 0 if self._last_label_us is None else now - self._last_label_us'),
           ('self._mass = self._mass * decay + 1.0','self._mass = self._mass * decay + sample_weight'),
           ('features[i] * response','sample_weight * features[i] * response'),
           ('features[i] * features[j]','sample_weight * features[i] * features[j]'),
           ('self._observations.append((now,mid,features))',
            'self._observations.append((now,mid,features,1.0 if spread<=1 else self.WIDE_TRAIN_WEIGHT))')]
    for old,new in pairs:
        assert base.count(old)==1,old
        base=base.replace(old,new,1)
    return {f'wide_weight{weight}':base.replace('    FEATURE_COUNT = 33',
            f'    WIDE_TRAIN_WEIGHT={weight}\n    FEATURE_COUNT = 33',1)
            for weight in (0.0,.25,.5)}


if __name__=='__main__':
    main(Path('logs/round2_t2_training_spread'),build(),
         'No-passive294098 learner observes all spreads but trades onlyspread1. Weight wide-spread training samples0/0.25/0.5, using spread stored at observation, not at maturity. No other model or execution change. Fixed3cases; same later-prefix criterion and native rules.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
