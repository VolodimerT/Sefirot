"""Occupied directory entries must refuse before network or quote staging."""
from contextlib import closing, contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sefirot.cli import main, write_quotes
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service


@contextmanager
def occupied_dangling_entry(path, missing):
    """Model the same lstat/exists distinction if Windows denies symlink creation."""
    native=True
    try:
        path.symlink_to(missing)
    except OSError as error:
        if os.name!='nt' or getattr(error,'winerror',None)!=1314:
            raise
        native=False
    if native:
        original_stat=path.lstat()
        original_link=(original_stat.st_dev,original_stat.st_ino,path.readlink())
        print('QUOTE_PREFLIGHT_ENTRY=NATIVE_DANGLING_SYMLINK',file=sys.stderr)
        try:
            yield True
        finally:
            current_stat=path.lstat()
            assert path.is_symlink()
            assert (current_stat.st_dev,current_stat.st_ino,path.readlink())==original_link
            path.unlink()
    else:
        print('QUOTE_PREFLIGHT_ENTRY=WINDOWS_MODELED_OCCUPIED_NAME',file=sys.stderr)
        original=os.path.lexists
        with patch('sefirot.cli.os.path.lexists',side_effect=lambda p:
                   True if Path(p)==path else original(p)):
            yield False


class QuoteOutputPreflightTests(unittest.TestCase):
    def test_cli_both_occupied_names_refuse_before_catalogue_price_or_credentials(self):
        with tempfile.TemporaryDirectory(prefix='owned-output-preflight-') as directory:
            root=Path(directory)
            database=root/'owned.sqlite'
            case=example(at=datetime.now(timezone.utc),match_id='owned-output-preflight')
            with closing(Repository(database)) as repo:
                prediction=Service(repo).capture(case['sports'],case['markets'])
            before=database.read_bytes()
            match=case['sports']['match']
            event={'id':'event1234','sport_key':'soccer_epl','home_team':match['home'],
                'away_team':match['away'],'commence_time':match['kickoff'],
                'bookmakers':[{'key':'testbook','markets':[{'key':'h2h',
                    'last_update':datetime.now(timezone.utc).isoformat(),
                    'outcomes':[{'name':match['home'],'price':2.1},{'name':'Draw','price':3.4},
                                {'name':match['away'],'price':3.8}]}]}]}
            for kind in ('quotes','receipt'):
                output=root/(kind+'.json')
                receipt=Path(str(output)+'.receipt.json')
                target=output if kind=='quotes' else receipt
                missing=root/'nonexistent-owned-target'
                args=['--db',str(database),'fetch-odds',prediction['id'],'--sport','soccer_epl',
                    '--event-id','event1234','--bookmaker','testbook','--rules-confirmed',
                    '--output',str(output)]
                with self.subTest(kind=kind), occupied_dangling_entry(target,missing) as native:
                    stdout,stderr=io.StringIO(),io.StringIO()
                    with patch('sefirot.odds_provider.events',return_value=[event]) as events, \
                         patch('sefirot.odds_provider.event_odds',return_value=event) as odds, \
                         patch('sefirot.odds_provider._api_key',side_effect=AssertionError('credential lookup')) as key, \
                         redirect_stdout(stdout),redirect_stderr(stderr):
                        self.assertEqual(main(args),2)
                        events.assert_not_called()
                        odds.assert_not_called()
                        key.assert_not_called()
                    self.assertIn('odds output already exists',stdout.getvalue()+stderr.getvalue())
                    self.assertFalse(output.exists())
                    self.assertFalse(receipt.exists())
                    self.assertFalse(missing.exists())
                    self.assertEqual(database.read_bytes(),before)
                    self.assertEqual(list(root.glob('.sefirot-*.staged')),[])
                    if native:
                        self.assertTrue(target.is_symlink())

    def test_direct_publication_refuses_both_occupied_names_before_staging(self):
        with tempfile.TemporaryDirectory(prefix='owned-publish-preflight-') as directory:
            root=Path(directory)
            for kind in ('quotes','receipt'):
                output=root/(kind+'.json')
                receipt=Path(str(output)+'.receipt.json')
                target=output if kind=='quotes' else receipt
                with self.subTest(kind=kind), occupied_dangling_entry(target,root/'absent'):
                    with patch('sefirot.cli.tempfile.NamedTemporaryFile',wraps=tempfile.NamedTemporaryFile) as staging:
                        with self.assertRaisesRegex(ValueError,'odds output already exists'):
                            write_quotes(output,{'quotes':[{'synthetic':True}],
                                'receipt':{'overround':1.04,'synthetic':True}})
                        staging.assert_not_called()
                    self.assertEqual(list(root.glob('.sefirot-*.staged')),[])
                    self.assertFalse((root/'absent').exists())


if __name__=='__main__':
    unittest.main()
