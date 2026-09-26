"""Local durable research ledger: foreign keys, immutability, and point-in-time scoring."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

from .system import canonical, digest, parse_time
from .markets import Market, settle, implied

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matches(id TEXT PRIMARY KEY, home TEXT NOT NULL REFERENCES teams(id), away TEXT NOT NULL REFERENCES teams(id), kickoff TEXT NOT NULL, league TEXT NOT NULL, CHECK(home != away));
CREATE TABLE IF NOT EXISTS markets(id TEXT PRIMARY KEY, kind TEXT NOT NULL, side TEXT NOT NULL, line REAL);
CREATE TABLE IF NOT EXISTS model_versions(id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('SHADOW','CANDIDATE','FROZEN')));
CREATE TABLE IF NOT EXISTS odds_snapshots(id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id), market_id TEXT NOT NULL REFERENCES markets(id), bookmaker TEXT NOT NULL, odds REAL NOT NULL CHECK(odds>1), received_at TEXT NOT NULL, phase TEXT NOT NULL CHECK(phase IN ('OPEN','FINAL','ENTRY')));
CREATE TABLE IF NOT EXISTS predictions(id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id), model_version TEXT NOT NULL REFERENCES model_versions(id), decision_at TEXT NOT NULL, input_digest TEXT NOT NULL, payload TEXT NOT NULL, sealed_hash TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS bets(id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES predictions(id), market_id TEXT NOT NULL REFERENCES markets(id), odds REAL NOT NULL CHECK(odds>1), stake REAL NOT NULL CHECK(stake>0), placed_at TEXT NOT NULL, origin TEXT NOT NULL CHECK(origin='EXTERNAL_LOG'));
CREATE TABLE IF NOT EXISTS results(match_id TEXT PRIMARY KEY REFERENCES matches(id), home_goals INTEGER NOT NULL CHECK(home_goals>=0), away_goals INTEGER NOT NULL CHECK(away_goals>=0), received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS closing_odds(id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id), market_id TEXT NOT NULL REFERENCES markets(id), bookmaker TEXT NOT NULL, odds REAL NOT NULL CHECK(odds>1), received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calibration_history(prediction_id TEXT NOT NULL REFERENCES predictions(id), market_id TEXT NOT NULL REFERENCES markets(id), brier REAL NOT NULL, probability REAL NOT NULL, actual INTEGER NOT NULL, PRIMARY KEY(prediction_id,market_id));
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE TRIGGER IF NOT EXISTS predictions_immutable_update BEFORE UPDATE ON predictions BEGIN SELECT RAISE(ABORT,'sealed prediction immutable'); END;
CREATE TRIGGER IF NOT EXISTS predictions_immutable_delete BEFORE DELETE ON predictions BEGIN SELECT RAISE(ABORT,'sealed prediction immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_immutable_update BEFORE UPDATE ON results BEGIN SELECT RAISE(ABORT,'result immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_immutable_delete BEFORE DELETE ON results BEGIN SELECT RAISE(ABORT,'result immutable'); END;
CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
CREATE INDEX IF NOT EXISTS idx_odds_match ON odds_snapshots(match_id,market_id,received_at);
"""


class ResearchStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def _log(self, at, event, payload):
        row = self.db.execute('SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1').fetchone()
        previous = row['hash'] if row else '0' * 64
        blob = canonical(payload)
        signature = digest([previous, at, event, blob])
        self.db.execute('INSERT INTO audit_logs(at,event,payload,previous_hash,hash) VALUES(?,?,?,?,?)', (at,event,blob,previous,signature))

    def record(self, event, decision):
        if decision['input_digest'] != digest(event) or decision['verdict'] != 'PASS':
            raise ValueError('only matching shadow decisions may be recorded')
        match_id = event['match_id']
        with self.db:
            home, away = [next(f['value'] for f in event['facts'] if f['key'] == k) for k in ('sports.home_team','sports.away_team')]
            for team in (home, away):
                self.db.execute('INSERT OR IGNORE INTO teams(id,name) VALUES(?,?)',(team,team))
            self.db.execute('INSERT INTO matches(id,home,away,kickoff,league) VALUES(?,?,?,?,?)',
                            (match_id,home,away,event['kickoff'],event.get('league','UNKNOWN')))
            model = decision['probability_seal']['model']
            self.db.execute("INSERT OR IGNORE INTO model_versions VALUES(?,?,'SHADOW')",(model,event['decision_at']))
            self.db.execute('INSERT INTO predictions VALUES(?,?,?,?,?,?,?)',
                            (decision['decision_digest'],match_id,model,event['decision_at'],decision['input_digest'],canonical(decision),decision['decision_digest']))
            for idx,q in enumerate(event.get('quotes',[])):
                market = Market(q['kind'],q['side'],q.get('line'))
                self.db.execute('INSERT OR IGNORE INTO markets VALUES(?,?,?,?)',(market.key,market.kind,market.side,market.line))
                self.db.execute('INSERT INTO odds_snapshots VALUES(?,?,?,?,?,?,?)',
                                (f'{match_id}:{idx}',match_id,market.key,q.get('bookmaker','MANUAL'),q['odds'],q['received_at'],q.get('phase','ENTRY')))
            self._log(event['decision_at'],'DECISION',{'match_id':match_id,'sealed_hash':decision['decision_digest']})

    def result(self, match_id, home, away, received_at):
        if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in (home,away)):
            raise ValueError('invalid score')
        match = self.db.execute('SELECT kickoff FROM matches WHERE id=?',(match_id,)).fetchone()
        if match is None or parse_time(received_at) <= parse_time(match['kickoff']):
            raise ValueError('result must arrive after kickoff')
        with self.db:
            self.db.execute('INSERT INTO results VALUES(?,?,?,?)',(match_id,home,away,received_at))
            for row in self.db.execute('SELECT id,payload,decision_at FROM predictions WHERE match_id=?',(match_id,)).fetchall():
                if parse_time(row['decision_at']) >= parse_time(match['kickoff']):
                    raise ValueError('late prediction')
                decision = json.loads(row['payload'])
                for c in decision['candidates']:
                    parts = c['market'].split(':')
                    market = Market(parts[0],parts[1],float(parts[2]) if len(parts)>2 else None)
                    actual = int(settle(market,home,away)=='WIN')
                    self.db.execute('INSERT INTO calibration_history VALUES(?,?,?,?,?)',
                                    (row['id'],market.key,(c['win_probability']-actual)**2,c['win_probability'],actual))
            self._log(received_at,'RESULT',{'match_id':match_id,'home':home,'away':away})

    def close(self, match_id, market, bookmaker, odds, received_at):
        implied(odds)
        kickoff = self.db.execute('SELECT kickoff FROM matches WHERE id=?',(match_id,)).fetchone()
        if kickoff is None or parse_time(received_at)>=parse_time(kickoff['kickoff']):
            raise ValueError('closing odds must precede kickoff')
        with self.db:
            self.db.execute('INSERT INTO closing_odds VALUES(?,?,?,?,?,?)',
                            (digest([match_id,market.key,bookmaker,received_at]),match_id,market.key,bookmaker,odds,received_at))
            self._log(received_at,'CLOSING_ODDS',{'match_id':match_id,'market':market.key,'odds':odds})

    def performance(self):
        rows = self.db.execute('''SELECT m.league,p.model_version,c.market_id,COUNT(*) n,AVG(c.brier) brier,
                         AVG(c.probability) forecast,AVG(c.actual) frequency
                         FROM calibration_history c JOIN predictions p ON p.id=c.prediction_id
                         JOIN matches m ON m.id=p.match_id GROUP BY m.league,p.model_version,c.market_id''').fetchall()
        return [dict(r) for r in rows]

    def clv(self):
        rows = self.db.execute('''SELECT o.match_id,o.market_id,o.odds entry,c.odds closing,
                         (o.odds/c.odds-1) clv FROM odds_snapshots o JOIN closing_odds c
                         ON c.match_id=o.match_id AND c.market_id=o.market_id AND c.bookmaker=o.bookmaker
                         WHERE o.phase='ENTRY' AND c.received_at>=o.received_at''').fetchall()
        return [dict(r) for r in rows]

    def verify_chain(self):
        previous = '0'*64
        for row in self.db.execute('SELECT * FROM audit_logs ORDER BY id'):
            if row['previous_hash'] != previous or row['hash'] != digest([previous,row['at'],row['event'],row['payload']]):
                return False
            previous = row['hash']
        return True
