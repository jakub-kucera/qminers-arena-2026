"""Read-only wrappers attribute fill quality; assert unchanged native result."""
import csv
import json
from pathlib import Path
import numpy as np
from scripts.benchmark import digest
from scripts.round2_workbench import load_manifest, run_candidate, write_json
from simulator import main as cli
from simulator.models import OrderStatus


def main():
    manifest = load_manifest(Path('logs/round2_local_intake'))
    path = Path('logs/round2_structural_batch/sources/robust_labels_3.py')
    destination = Path('logs/round2_fill_diagnostics')
    destination.mkdir(exist_ok=True)
    source = cli.load_strategy_from_file(path)
    public = source.on_order_book_change
    private = source.on_private_order_update
    quotes, fills = [], []
    last = [None]

    def on_public(snapshot, trades):
        public(snapshot, trades)
        bid = next((o.price for o in snapshot.bids if o.owner == 'market'), None)
        ask = next((o.price for o in snapshot.asks if o.owner == 'market'), None)
        if bid is None or ask is None or bid >= ask:
            last[0] = None
            return
        mid = (bid+ask)/2
        features = source._observations[-1][2] if source._observations else ()
        forecast = sum(w*x for w,x in zip(source._weights, features))
        state = (snapshot.timestamp_us, mid, ask-bid, forecast, source.inventory)
        last[0] = state
        if not quotes or snapshot.timestamp_us-quotes[-1][0] >= 5000:
            quotes.append(state)

    def on_private(event):
        record = source._orders.get(event.order_id)
        if event.status in (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED) and record and last[0]:
            state = last[0]
            fills.append((event.timestamp_us, record[0], event.filled_quantity,
                          event.fill_price, *state, event.timestamp_us-record[-1]))
        private(event)

    source.on_order_book_change = on_public
    source.on_private_order_update = on_private
    # Preserve the same audited evaluation and native configuration, using an
    # already constructed strategy. No observations enter the trading model.
    from scripts.benchmark import evaluate
    from scripts.round2_workbench import BoundaryMarkEngine
    BoundaryMarkEngine.boundaries = (manifest['development_cutoff_us'],)
    result = evaluate(source, Path(manifest['development']), destination, 600, BoundaryMarkEngine)
    reference = json.loads(Path('logs/round2_structural_batch/results.json').read_text())['robust_labels_3']
    assert result['result'] == reference['result'], 'Instrumentation changed trading'
    q = np.array(quotes);f = np.array(fills)
    np.savez_compressed(destination/'observations.npz', quotes=q, fills=f)
    horizons = {}
    for h in (5000,20000,100000,400000,2000000,5000000):
        idx = np.searchsorted(q[:,0], f[:,0]+h)
        valid = idx < len(q)
        idx = np.minimum(idx,len(q)-1)
        valid &= q[idx,0]-(f[:,0]+h) <= 20000
        edge = f[:,1]*(q[idx,1]-f[:,3])
        groups = {}
        for name,mask in [('all',valid), ('small',valid & (f[:,2]<=20)),
                          ('large',valid & (f[:,2]>20)),
                          ('aligned_forecast',valid & (f[:,1]*f[:,7]>.3)),
                          ('opposed_forecast',valid & (f[:,1]*f[:,7]<-.3))]:
            weights=f[mask,2]
            groups[name] = dict(private_fill_events=int(mask.sum()), volume=float(weights.sum()),
                               markout_per_lot=float(np.average(edge[mask],weights=weights)) if weights.sum() else None)
        horizons[str(h)] = groups
    report = dict(scope='First 60% public development only; overlapping markouts are descriptive.',
                  source_sha256=digest(path),data_sha256=manifest['development_sha256'],
                  exact_result_parity=True,result=result['result'],horizons=horizons,
                  fill_count_definition='Native fills counts distinct filled order IDs; private callbacks can include several partial fills per order.',
                  caveat='Prefill state is the last public callback; future sampled midpoint within 20 ms of target. Markouts are not completed round-trip PnL.')
    write_json(destination/'summary.json',report)
    print(json.dumps(report,indent=2))


if __name__ == '__main__':main()
