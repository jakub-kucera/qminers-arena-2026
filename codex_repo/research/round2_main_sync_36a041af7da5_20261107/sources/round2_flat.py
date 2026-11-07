"""No-trade control for round-2 evaluation; zero-risk reference, not a forecast model."""
from simulator.strategy import BaseStrategy


class FlatStrategy(BaseStrategy):
    POSITION_LIMIT=100

    def __init__(self):
        super().__init__()
        self.inventory=0
        self.cash=0

    def on_order_book_change(self,snapshot,trades):
        pass

    def on_private_order_update(self,event):
        pass
