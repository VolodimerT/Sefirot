"""Release artifacts must not label unexecuted tests as successful."""
from contextlib import redirect_stdout
import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from scripts import verify_release as release


class CapturedOutput(io.StringIO):
    def reconfigure(self, **kwargs): pass


class ReleaseSkipAccountingTests(unittest.TestCase):
    def test_realistic_skipped_summary_is_preserved_in_both_release_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'examples').mkdir()
            for name in ['core2_backtest.json','audit_cases_20260927_30.json']:
                (root/'examples'/name).write_text('[]')
            results=[SimpleNamespace(returncode=0,stdout='',stderr='test_native ... skipped \'native PostgreSQL unavailable\'\n\nRan 1632 tests in 139.755s\n\nOK (skipped=9)\n'),
                     SimpleNamespace(returncode=0,stderr='',stdout=json.dumps({'integrity':True,'replay_matches':True}))]
            backtest={'fixtures':12,'metrics':{'n':84}}
            audit={'cases':0,'outcomes':{},'dataset_hash':'0'*64,'holdout_eligible':False}
            with patch.object(release,'ROOT',root),patch.object(release,'subprocess',SimpleNamespace(run=Mock(side_effect=results))), \
                 patch.object(release,'walk_forward',return_value=backtest), \
                 patch.object(release,'audit_cases',return_value=audit),redirect_stdout(CapturedOutput()):
                self.assertEqual(release.main(),0)
            record=json.loads((root/'reports/RELEASE_CHECK.json').read_text(encoding='utf-8'))
            self.assertEqual(record['tests'],1632)
            self.assertEqual(record['tests_passed'],1623)
            self.assertEqual(record['tests_skipped'],9)
            text=(root/'reports/TEST_REPORT.md').read_text(encoding='utf-8')
            self.assertIn('1623',text);self.assertIn('пропущено **9**',text)
            self.assertNotIn('1632/1632',text)

    def test_successful_unskipped_suite_has_explicit_zero(self):
        self.assertEqual(release.test_counts('Ran 20 tests in 1.0s\n\nOK\n'),
                         {'tests':20,'tests_passed':20,'tests_skipped':0})

    def test_missing_failed_zero_or_inconsistent_summary_does_not_certify_release(self):
        for text in ['OK\n','Ran 0 tests in 0s\nOK\n',
                     'Ran 2 tests in 1s\nOK (skipped=3)\n',
                     'Ran 2 tests in 1s\nFAILED (failures=1)\n',
                     'Ran 2 tests in 1s\nOK\nRan 3 tests in 1s\nOK\n']:
            with self.subTest(summary=text),self.assertRaises(ValueError):release.test_counts(text)
