"""Run from Windows: py -3 sefirot.py demo.

When imported as sefirot from the repository root, expose the real package
path as well. This avoids the launcher file shadowing src/sefirot in
service runtimes that import package submodules with python -c.
"""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'src'
sys.path.insert(0,str(SRC))
if __name__=='sefirot':
    __path__=[str(SRC/'sefirot')]
    __package__='sefirot'

from sefirot.cli import main

if __name__=='__main__':
    raise SystemExit(main())
