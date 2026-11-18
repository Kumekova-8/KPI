from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


class DB:
    def __init__(self, location=None):
        self.location = str(location or os.getenv('KPI_DATABASE',ROOT/'runtime'/'kpi.sqlite3'))
        self.postgres = self.location.startswith(('postgresql://','postgres://'))
        if not self.postgres:
            Path(self.location).parent.mkdir(parents=True,exist_ok=True)

    @contextmanager
    def transaction(self, write=False):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(self.location,row_factory=dict_row)
        else:
            connection = sqlite3.connect(self.location,timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
        tx = Transaction(connection,self.postgres)
        try:
            if write:
                if self.postgres:
                    tx.query('SELECT pg_advisory_xact_lock(85172801)')
                else:
                    tx.query('BEGIN IMMEDIATE')
            yield tx
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self):
        with self.transaction(write=True) as tx:
            tx.query('CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)')
            done = {row['name'] for row in tx.all('SELECT name FROM migrations')}
            for path in sorted((ROOT/'migrations').glob('*.sql')):
                if path.name not in done:
                    for statement in path.read_text('utf8').split(';'):
                        if statement.strip():
                            tx.query(statement)
                    tx.query('INSERT INTO migrations VALUES (?)',(path.name,))


class Transaction:
    def __init__(self,connection,postgres):
        self.connection = connection
        self.postgres = postgres

    def query(self,sql,params=()):
        if self.postgres:
            sql = sql.replace('?','%s')
        return self.connection.execute(sql,params)

    def all(self,sql,params=()):
        return [dict(row) for row in self.query(sql,params).fetchall()]

    def one(self,sql,params=()):
        row = self.query(sql,params).fetchone()
        return dict(row) if row is not None else None

    def insert(self, table, values):
        columns = ','.join(values)
        params = ','.join('?' for _ in values)
        self.query(f'INSERT INTO {table} ({columns}) VALUES ({params})',tuple(values.values()))

    def update(self, table, key, values):
        updates = ','.join(f'{col}=?' for col in values)
        self.query(f'UPDATE {table} SET {updates} WHERE id=?',(*values.values(),key))

