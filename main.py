"""
PyCrucible entry point.
Delegates straight to the installed spyde package so all relative imports work.
"""
from spyde.__main__ import main

if __name__ == "__main__":
    main()

