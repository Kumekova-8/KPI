"""Create and verify an online backup of a local SQLite demonstration database."""
from argparse import ArgumentParser
from pathlib import Path
import sqlite3


def backup(source,destination):
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as live:
            with sqlite3.connect(destination) as copy:
                live.backup(copy)
                if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise RuntimeError('Backup failed integrity check')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


if __name__=='__main__':
    parser=ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    backup(args.source.resolve(),args.destination.resolve())
    print(args.destination.resolve())

