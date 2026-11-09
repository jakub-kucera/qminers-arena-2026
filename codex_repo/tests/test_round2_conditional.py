import tempfile
import unittest
from pathlib import Path

from scripts.round2_conditional_market_fills import conditional_model
from simulator.main import load_strategy_from_file
from simulator.models import Trade


class ConditionalFillTests(unittest.TestCase):
    def strategy(self):
        source=conditional_model(Path('strategies/round2/round2_transfer.py').read_text(),100000,'gate')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.py';p.write_text(source)
            return load_strategy_from_file(p)

    def test_markout_label_cannot_mature_early(self):
        s=self.strategy();frame=s._conditional_features(1,.5,(0,)*29)
        s._conditional_pending.append((0,1,99,frame,10))
        s._learn_conditional(99999,101,[])
        self.assertEqual(s._conditional_labels,0)
        self.assertEqual(s._conditional_mass,0)
        s._learn_conditional(100000,101,[])
        self.assertEqual(s._conditional_labels,1)
        self.assertEqual(s._conditional_xy[0],20)

    def test_trade_uses_preceding_features_and_groups_partial_matches(self):
        s=self.strategy();features=tuple(i/100 for i in range(29))
        s._conditional_previous=(0,99,101,features)
        trades=[Trade(timestamp_us=1000,price=99,quantity=q,maker_order_id='m'+str(q),
            taker_order_id='t',maker_owner='market',taker_owner='market',book_side='bid') for q in (10,15)]
        s._learn_conditional(1000,100,trades)
        self.assertEqual(len(s._conditional_pending),1)
        stamp,sign,price,frame,weight=s._conditional_pending[0]
        self.assertEqual((stamp,sign,price,weight),(1000,1,99,20))
        self.assertEqual(frame,s._conditional_features(1,1,features))


if __name__=='__main__':unittest.main()
