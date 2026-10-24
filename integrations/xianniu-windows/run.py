"""Source entry point; the frozen executable uses the same main()."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'src'), str(ROOT.parent / 'xianniu-router' / 'src')]
from starpass_xianniu.app import main

if __name__ == '__main__':
    raise SystemExit(main())
