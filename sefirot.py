"""Run from Windows: py -3 sefirot.py demo"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from sefirot.cli import main
if __name__=='__main__':raise SystemExit(main())
