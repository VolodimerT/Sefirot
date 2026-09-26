"""Run the test suite from any working directory."""

from pathlib import Path
import sys
import unittest


def main() -> int:
    root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(start_dir=str(root / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
