import tempfile
import unittest
from pathlib import Path

from scripts.round2_next_move import next_move
from simulator.main import load_strategy_from_file


class NextMoveTests(unittest.TestCase):
    def strategy(self,event):
        text=next_move(Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text(),event,.5)
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'s.py';p.write_text(text);return load_strategy_from_file(p)

    def test_event_label_uses_latest_past_frame_only_after_price_moves(self):
        s=self.strategy(True)
        s._observations.append((0,100,(1.0,)*29));s._observations.append((20000,100,(2.0,)*29))
        s._learn(100000,100)
        self.assertEqual(s._labels,0)
        s._learn(100001,100.5)
        self.assertEqual(s._labels,1)
        self.assertEqual(s._xy[0],1)

    def test_stale_frame_is_discarded(self):
        s=self.strategy(False);s._observations.append((0,100,(1.0,)*29))
        s._learn(6000000,101)
        self.assertEqual(s._labels,0)


if __name__=='__main__':unittest.main()
