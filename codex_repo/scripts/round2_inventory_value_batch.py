"""Robust 400ms maker: inventory price control, without target-size cancel churn."""
from pathlib import Path
from scripts.round2_structural_batch import run


def build():
    base = Path('logs/round2_structural_batch/sources/robust_labels_3.py').read_text()
    cases = {}
    for skew in (.25, 1.0):
        cases[f'skew_{str(skew).replace(".","p")}'] = base.replace(
            'skew = 0.025 * self.inventory/100', f'skew = {skew} * self.inventory/100')
    for hold in (200000,1000000):
        text = base.replace('self.inventory = 0','self.inventory = 0\n        self._inventory_since = None',1)
        text = text.replace('            self.inventory += record[0]*event.filled_quantity',
            '''            old_inventory = self.inventory
            self.inventory += record[0]*event.filled_quantity
            if old_inventory*self.inventory <= 0:
                self._inventory_since = event.timestamp_us if self.inventory else None''')
        marker = '        # Withdraw the side vulnerable'
        policy = f'''        # An old position with contrary alpha may pay the spread to exit.
        if (self._inventory_since is not None and now-self._inventory_since >= {hold}
                and spread <= 2 and self.inventory*prediction < -0.3*abs(self.inventory)):
            if self.inventory > 0:
                buy = None
                sell = bid
            elif self.inventory < 0:
                sell = None
                buy = ask
'''
        text = text.replace(marker,policy+marker)
        # Cap an aggressive reduction at flat, keeping other reservations.
        text = text.replace('        quantity=min(self.QUOTE_SIZE,100-sign*self.inventory-effective,',
            '''        reducing = ((sign < 0 and self._cached_bid is not None and price <= self._cached_bid)
                    or (sign > 0 and self._cached_ask is not None and price >= self._cached_ask))
        planned = max(0,-sign*self.inventory) if reducing else 100-sign*self.inventory
        quantity=min(self.QUOTE_SIZE,planned-effective,''')
        cases[f'contrary_exit_{hold//1000}ms'] = text
    return cases


if __name__ == '__main__':
    run(Path('logs/round2_inventory_value_batch'),build(),[
        'Inventory skew changes reservation prices without repeated quantity cancel/replace',
        'Bounded aggressive reduction at flat for old positions with contrary forecast',
        'All original native costs, latency, reservations and 100-lot hard strategy budget remain'])
