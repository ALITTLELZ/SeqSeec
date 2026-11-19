# File: seqseec/__main__.py
# Version: 0.1.0
# Last modified: 2026-11-19 (XD)
# Change: Allow `python -m seqseec ...` as well as the installed `seqseec` command.
import sys

from seqseec.cli import main

sys.exit(main())
