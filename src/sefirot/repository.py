"""Transactional append-only local ledger. Hashes detect accidents, not hostile admins."""
from __future__ import annotations
import json
import sqlite3
from .contracts import canonical,digest,time,text
from .ledger_integrity import validate_row

TABLES=('teams','matches','markets','odds_snapshots','predictions','bets','results','closing_odds',
        'calibration_history','model_versions','audit_logs','decisions','postmortems','health_events',
        'calibrators','validation_runs','split_assignments','overrides','policy_approvals','model_routes','postmatch_reports','jobs')

SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matches(id TEXT PRIMARY KEY, home TEXT NOT NULL REFERENCES teams(id), away TEXT NOT NULL REFERENCES teams(id), kickoff TEXT NOT NULL, league TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS markets(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_versions(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS predictions(id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id), model_id TEXT NOT NULL REFERENCES model_versions(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES predictions(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS odds_snapshots(id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES predictions(id), market_id TEXT NOT NULL REFERENCES markets(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bets(id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decisions(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY REFERENCES matches(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS closing_odds(id TEXT PRIMARY KEY, match_id TEXT NOT NULL REFERENCES matches(id), market_id TEXT NOT NULL REFERENCES markets(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calibration_history(id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES predictions(id), market_id TEXT NOT NULL REFERENCES markets(id), at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(prediction_id,market_id));
CREATE TABLE IF NOT EXISTS postmatch_reports(id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decisions(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS postmortems(id TEXT PRIMARY KEY, decision_id TEXT NOT NULL REFERENCES decisions(id), at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS health_events(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calibrators(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS validation_runs(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS split_assignments(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overrides(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_routes(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policy_approvals(id TEXT PRIMARY KEY, at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
CREATE INDEX IF NOT EXISTS predictions_match ON predictions(match_id,at);
CREATE INDEX IF NOT EXISTS decision_prediction ON decisions(prediction_id,at);
CREATE INDEX IF NOT EXISTS metrics_prediction ON calibration_history(prediction_id,at);
PRAGMA user_version=2;
'''


class Repository:
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self._savepoint_sequence=0
        if self.db.execute('PRAGMA user_version').fetchone()[0] not in (0,2): raise ValueError('unsupported database version')
        self.db.executescript(SCHEMA)
        for table in TABLES:
            for op in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable ledger'); END")

    def close(self): self.db.close()

    def transaction(self): return Transaction(self)

    def insert(self,table,identifier,payload,**columns):
        if table not in TABLES or table=='audit_logs': raise ValueError('invalid ledger table')
        existing=self.db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone()
        blob=canonical(payload)
        if existing:
            if existing['payload']!=blob or any(existing[k]!=v for k,v in columns.items()): raise ValueError('immutable record conflict')
            return False
        names=['id','payload']+list(columns)
        if any(k not in {'at','match_id','prediction_id','decision_id','model_id','market_id','home','away','kickoff','league'} for k in columns): raise ValueError('invalid storage column')
        self.db.execute(f"INSERT INTO {table}({','.join(names)}) VALUES({','.join('?' for _ in names)})",[identifier,blob]+list(columns.values()))
        return True

    def get(self,table,identifier):
        if table not in TABLES or table=='audit_logs': raise ValueError('invalid ledger table')
        row=self.db.execute(f'SELECT payload FROM {table} WHERE id=?',(identifier,)).fetchone()
        if row is None: raise ValueError(f'{table} record not found: {identifier}')
        return json.loads(row['payload'])

    def all(self,table,as_of=None):
        if table not in TABLES or table=='audit_logs': raise ValueError('invalid ledger table')
        rows=self.db.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
        return [json.loads(r['payload']) for r in rows if as_of is None or ('at' in r.keys() and time(r['at'])<=time(as_of))]

    def log(self,event,at,payload):
        time(at);text(event,'event')
        last=self.db.execute('SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1').fetchone()
        prev=last['hash'] if last else '0'*64
        data=canonical(payload); hash_=digest([prev,at,event,data])
        self.db.execute('INSERT INTO audit_logs(at,event,payload,previous_hash,hash) VALUES(?,?,?,?,?)',(at,event,data,prev,hash_))

    def verify(self):
        try:
            if self.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':return False
            if self.db.execute('PRAGMA foreign_key_check').fetchone():return False
            for table in TABLES:
                for row in self.db.execute(f'SELECT * FROM {table}'):
                    validate_row(table,row)
            prev='0'*64; referenced=set()
            for sequence,row in enumerate(self.db.execute('SELECT * FROM audit_logs ORDER BY id'),1):
                if row['id']!=sequence or row['previous_hash']!=prev or row['hash']!=digest([prev,row['at'],row['event'],row['payload']]):return False
                prev=row['hash'];payload=json.loads(row['payload'])
                if 'record_table' in payload:
                    record=self.get(payload['record_table'],payload['record_id'])
                    if digest(record)!=payload['record_hash']:return False
                    referenced.add((payload['record_table'],payload['record_id']))
            # Every probability and decision must have a content-bound audit event.
            for table in ('predictions','decisions','results','calibrators','validation_runs','bets'):
                if any((table,r['id']) not in referenced for r in self.db.execute(f'SELECT id FROM {table}')):return False
            return True
        except (ValueError,KeyError,TypeError,OverflowError,sqlite3.Error):
            return False

    def record_log(self,table,identifier,at,payload):
        self.log('RECORD',at,{'record_table':table,'record_id':identifier,'record_hash':digest(payload)})


class Transaction:
    def __init__(self,repo): self.repo=repo;self.savepoint=None
    def __enter__(self):
        if self.repo.db.in_transaction:
            self.repo._savepoint_sequence+=1
            self.savepoint=f'sefirot_{self.repo._savepoint_sequence}'
            self.repo.db.execute(f'SAVEPOINT {self.savepoint}')
        else:
            self.repo.db.execute('BEGIN IMMEDIATE')
        return self.repo
    def __exit__(self,typ,value,tb):
        if self.savepoint:
            if typ:self.repo.db.execute(f'ROLLBACK TO SAVEPOINT {self.savepoint}')
            self.repo.db.execute(f'RELEASE SAVEPOINT {self.savepoint}')
        else:
            try:self.repo.db.execute('ROLLBACK' if typ else 'COMMIT')
            except sqlite3.Error:
                if self.repo.db.in_transaction:self.repo.db.execute('ROLLBACK')
                raise
