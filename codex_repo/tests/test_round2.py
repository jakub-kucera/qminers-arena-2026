import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from scripts.benchmark import digest
from scripts.build_round2_candidates import BASE, DESTINATION, candidates
from scripts.check_submission import check
from scripts.round2_workbench import BoundaryMarkEngine, batch, load_manifest, prepare, select, final
from simulator.main import load_strategy_from_file
from simulator.models import OrderRequest, OrderStatus, OrderType, Side
from simulator.simulator import ExchangeSimulator, SimulationConfig
from simulator.strategy import BaseStrategy
from test_strategy import Gateway, RISK_CONFIG, HEADER


class PaidOnce(BaseStrategy):
    POSITION_LIMIT=1000

    def __init__(self):
        super().__init__();self.inventory=0;self.cash=0

    def on_order_book_change(self,snapshot,trades):
        if snapshot.timestamp_us==1:
            self.send_order(OrderRequest(side=Side.BUY,price=101,quantity=200,order_type=OrderType.IOC))

    def on_private_order_update(self,event):
        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED):
            self.inventory+=event.filled_quantity
            self.cash-=event.filled_quantity*event.fill_price


class Round2CandidateTests(unittest.TestCase):
    def test_generated_standalone_files_and_transfer_body_are_preserved(self):
        import ast
        for name,(source,risk,_) in candidates().items():
            path=DESTINATION/(name+'.py')
            self.assertEqual(path.read_text(),source)
            self.assertEqual(check(path),[])
            s=load_strategy_from_file(path)
            self.assertEqual((s.inventory,s.cash),(0,0))
        archived=ast.parse(BASE.read_text()).body[1:]
        transfer=ast.parse((DESTINATION/'round2_transfer.py').read_text()).body[1:]
        self.assertEqual(ast.dump(ast.Module(body=archived,type_ignores=[])),
                         ast.dump(ast.Module(body=transfer,type_ignores=[])))

    def test_strict_maker_keeps_pending_cancel_reserved(self):
        s=load_strategy_from_file(DESTINATION/'round2_strict100.py');g=Gateway(s);cancels=[]
        s._ctx.cancel_order=cancels.append
        s._quote(0,1,99);first=next(iter(s._orders));s._orders[first][3]=True
        s._quote(6000,1,98)
        self.assertEqual(cancels,[first])
        self.assertEqual(len(g.sent),1)
        self.assertEqual(sum(r[2] for r in s._orders.values() if r[0]>0),100)

    def test_dual_errors_and_labels_do_not_update_before_maturity(self):
        s=load_strategy_from_file(DESTINATION/'round2_dual_memory.py')
        row=(1.0,)+(0.0,)*(s.FEATURE_COUNT-1)
        s._observations.append((0,100,row,1.0,-1.0))
        original=(s._long_loss,s._fast_loss)
        s._learn(s.HORIZON_US-1,101)
        self.assertEqual(s._labels,0);self.assertEqual((s._long_loss,s._fast_loss),original)
        s._learn(s.HORIZON_US,101)
        self.assertEqual(s._labels,1)
        self.assertLess(s._long_loss,s._fast_loss)

    def test_dual_memory_can_shift_toward_faster_forecast_after_reversal(self):
        parent=load_strategy_from_file(DESTINATION/'round2_dual_memory.py').__class__
        class Tiny(parent):
            FEATURE_COUNT=1
            FAST_MEMORY_US=10000000
            MIN_LABELS=5
            SCORE_ALPHA=0.05
        s=Tiny()
        for i in range(160):
            now=i*1000000
            response=1 if i<100 else -1
            long_pred=s._forecast_for(s._long_weights,(1.0,))
            fast_pred=s._forecast_for(s._fast_weights,(1.0,))
            s._observations.append((now-s.HORIZON_US,100,(1.0,),long_pred,fast_pred))
            s._learn(now,100+response)
        self.assertLess(s._fast_weights[0],s._long_weights[0])
        self.assertGreater(s._fast_mix,0.5)
        self.assertTrue(all(math.isfinite(v) for v in s._weights))


class Round2WorkbenchTests(unittest.TestCase):
    def tape(self,directory):
        p=Path(directory)/'tape.csv'
        rows=HEADER+'0,Insert,b,B,1000,99,G\n0.000001,Insert,a,A,1000,101,G\n'
        rows+=''.join(f'{i},Cancel,unknown,,,,\n' for i in range(1,11))
        p.write_text(rows)
        return p

    def test_prepare_snapshots_sources_splits_time_groups_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.tape(folder)
            with p.open() as stream:rows=list(csv.reader(stream))
            rows.insert(8,['6','Cancel','another','','','',''])
            rows.insert(11,['8','Cancel','another','','','',''])
            with p.open('w',newline='') as f:csv.writer(f).writerows(rows)
            out=Path(folder)/'run'
            m=prepare(p,out,[DESTINATION/'round2_flat.py'])
            for key,cut in (('development',m['development_cutoff_us']),('validation_prefix',m['validation_cutoff_us'])):
                with Path(m[key]).open() as f:
                    self.assertTrue(all(float(r['Time'])*1000000<cut for r in csv.DictReader(f)))
            self.assertEqual(load_manifest(out)['data_sha256'],digest(p))
            frozen=Path(m['candidates'][0]['file']);frozen.write_text(frozen.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'snapshot changed'):load_manifest(out)

    def test_prepare_rejects_nonmonotonic_time_and_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.tape(folder);out=Path(folder)/'run'
            prepare(p,out,[DESTINATION/'round2_flat.py'])
            with self.assertRaisesRegex(ValueError,'not empty'):prepare(p,out)
            p.write_text(HEADER+'1,Cancel,x,,,,\n0,Cancel,x,,,,\n2,Cancel,x,,,,\n')
            with self.assertRaisesRegex(ValueError,'not monotonic'):prepare(p,Path(folder)/'other')

    def test_boundary_marks_do_not_change_any_native_field_even_with_penalties(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'tape.csv'
            p.write_text(HEADER+'0,Insert,b,B,1000,99,G\n0.000001,Insert,a,A,1000,101,G\n'
                         '0.020000,Cancel,unknown,,,,\n0.030000,Cancel,unknown,,,,\n')
            BoundaryMarkEngine.boundaries=(12500,)
            observed=BoundaryMarkEngine(PaidOnce(),SimulationConfig(**RISK_CONFIG))
            r=observed.run(p)
            plain=ExchangeSimulator(PaidOnce(),SimulationConfig(**RISK_CONFIG)).run(p)
            self.assertEqual(r.model_dump(),plain.model_dump())
            self.assertAlmostEqual(observed.boundary_pnl['12500'],-474.99)

    def test_sparse_prefix_carries_paid_exposure_to_exact_split_without_changing_result(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'tape.csv'
            p.write_text(HEADER+'0,Insert,b,B,1000,99,G\n0.000001,Insert,a,A,1000,101,G\n'
                         '0.020000,Cancel,unknown,,,,\n')
            BoundaryMarkEngine.boundaries=(30000,)
            observed=BoundaryMarkEngine(PaidOnce(),SimulationConfig(**RISK_CONFIG))
            r=observed.run(p)
            plain=ExchangeSimulator(PaidOnce(),SimulationConfig(**RISK_CONFIG)).run(p)
            self.assertEqual(r.model_dump(),plain.model_dump())
            self.assertEqual(observed.current_ts_us,20000)
            self.assertAlmostEqual(observed.boundary_pnl['30000'],-649.99)

    def test_final_requires_selection_and_refuses_modified_frozen_source(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'run';m=prepare(self.tape(folder),out,[DESTINATION/'round2_flat.py'])
            with self.assertRaisesRegex(ValueError,'Finish screen'):select(m,out,1)
            with self.assertRaises(FileNotFoundError):final(m,out)
            candidate=m['candidates'][0];frozen=out/'frozen_submission.py'
            frozen.write_bytes(Path(candidate['file']).read_bytes())
            (out/'selection.json').write_text(json.dumps(dict(name=candidate['name'],risk=candidate['risk'],
                frozen_file=str(frozen),source_sha256=candidate['source_sha256'],data_sha256=m['data_sha256'])))
            frozen.write_text(frozen.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'winner changed'):final(m,out)

    def test_paid_workflow_freezes_and_matches_unmodified_cli(self):
        import inspect
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'paid_toy.py'
            source.write_text('from simulator.strategy import BaseStrategy\n'
                'from simulator.models import OrderRequest, OrderStatus, OrderType, Side\n\n'
                +inspect.getsource(PaidOnce))
            out=Path(folder)/'run';m=prepare(self.tape(folder),out,[source])
            batch(m,out,'development',1)
            selected=select(m,out,1)
            self.assertFalse(selected['final_segment_inspected'])
            self.assertEqual(digest(selected['frozen_file']),digest(source))
            validation=json.loads((out/'validation.json').read_text())['results']['paid_toy']
            self.assertAlmostEqual(validation['validation_pnl_increment'],-20000)
            report=final(m,out)
            self.assertTrue(report['official_cli_match'])
            self.assertGreater(report['result']['result']['breach_penalty'],0)
            self.assertAlmostEqual(report['final_segment_pnl_increment'],-20000)
            stamp=(out/'final_report.json').stat().st_mtime_ns
            self.assertEqual(final(m,out),report)
            self.assertEqual((out/'final_report.json').stat().st_mtime_ns,stamp)


if __name__=='__main__':unittest.main()
