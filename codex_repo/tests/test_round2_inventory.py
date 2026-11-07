import tempfile
import unittest
from pathlib import Path

from scripts.round2_inventory_probes import build_candidates
from simulator.main import load_strategy_from_file
from simulator.models import BookOrderView,OrderBookSnapshot,Side
from test_strategy import Gateway


class InventoryPolicyTests(unittest.TestCase):
    def strategy(self,name):
        sources=build_candidates(Path('strategies/round1_quote_flow_624076.py').read_text())
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'candidate.py';p.write_text(sources[name]);s=load_strategy_from_file(p)
        g=Gateway(s);return s,g

    def test_fresh_quotes_respect_both_planned_bounds(self):
        s,g=self.strategy('round2_target_band25')
        s._upper_target=25;s._lower_target=-25
        s._quote(0,1,99);s._quote(0,-1,101)
        self.assertEqual([r.quantity for r in g.sent],[25,25])

    def test_shrinking_target_does_not_erase_real_pending_cancel_quantity(self):
        s,g=self.strategy('round2_target_band25');canceled=[];s._ctx.cancel_order=canceled.append
        s._quote(0,1,99);old=next(iter(s._orders));s._orders[old][3]=True
        s._upper_target=25;s._quote(6000,1,99)
        self.assertEqual(canceled,[old])
        self.assertEqual(s._orders[old][2],100)
        self.assertEqual(sum(r[2] for r in s._orders.values()),125)
        self.assertEqual(g.sent[-1].quantity,25)

    def test_selective_policy_only_opens_in_confident_direction(self):
        for weight,expected_side,expected_bounds in ((0,None,(0,0)),(1,Side.BUY,(100,0)),(-1,Side.SELL,(0,-100))):
            s,g=self.strategy('round2_selective_entry');s._labels=s.MIN_LABELS;s._last_fit_us=0
            s._weights[2]=weight
            s.on_order_book_change(OrderBookSnapshot(1,
                [BookOrderView('b',Side.BUY,100,300,'market')],
                [BookOrderView('a',Side.SELL,101,100,'market')]),[])
            self.assertEqual((s._upper_target,s._lower_target),expected_bounds)
            self.assertEqual([r.side for r in g.sent],[] if expected_side is None else [expected_side])


if __name__=='__main__':unittest.main()
