"""Synthetic scheduled cycle and private checkpoint restart."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.prospective_schedule import tick
from scripts.shadow_checkpoint import pack, restore
from sefirot.contracts import time
from sefirot.repository import Repository
from sefirot.service import Service
from test_operations_upgrade import row, stamp
import test_prospective_shadow as synthetic


class ProspectiveScheduleTest(unittest.TestCase):
    def test_cycle_resumes_after_source_outage_and_checkpoint_restore(self):
        scenario = synthetic.ProspectiveShadowTests()
        scenario.setUp()
        self.addCleanup(scenario.doCleanups)
        scenario.stage()
        config = dict(league=9, profile='MEN', reliability=.95, synthetic_test_only=True)
        outage = tick(scenario.service, None, **config)
        self.assertEqual(outage['reason'], 'SOURCE_UNAVAILABLE')
        scenario.restart()
        self.assertFalse(tick(scenario.service, scenario.sources, **config)['ran'])
        scenario.now = time(stamp(.25))
        captured = tick(scenario.service, scenario.sources, **config)
        self.assertEqual(captured['report']['counts'], {'AWAITING_FT': 1})
        self.assertEqual(captured['network_requests'], 0)
        scenario.now = time(stamp(6))
        scenario.put([row(100, hours=3, score=(1, 1))], 6, exact=True)
        with TemporaryDirectory() as workspace:
            folder = Path(workspace)
            scenario.sources.close()
            scenario.repo.close()
            (scenario.base / 'source.sqlite').rename(scenario.base / 'sources.sqlite')
            archive = folder / 'saved.zip'
            pack(scenario.base, archive)
            restored = folder / 'restored'
            restore(restored, archive)
            with closing(Repository(restored / 'shadow.sqlite')) as ledger, closing(
                    Repository(restored / 'sources.sqlite', read_only=True)) as source:
                svc = Service(ledger, clock=lambda: scenario.now)
                result = tick(svc, source, **config)
                self.assertEqual(result['report']['counts'], {'SETTLED': 1})
                self.assertEqual(result['report']['scored_original_fixtures'], 0)
                self.assertTrue(result['report']['metrics'])
                self.assertFalse(tick(svc, source, **config)['ran'])
                self.assertEqual(len(ledger.all('results')), 1)
                self.assertEqual(len(ledger.all('predictions')), 1)
                self.assertTrue(ledger.verify())
