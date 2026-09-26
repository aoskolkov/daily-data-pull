"""Entry point — run from repo root as: python wrdsdl.py <command> [args]"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.cli import main

if __name__ == "__main__":
    main()
