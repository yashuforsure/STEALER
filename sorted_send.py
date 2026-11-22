"""sorted_send.py - compatibility shim for the old option-1 command.

The picker is PC-wise now. Everything is implemented in sender_send.py.
"""

from sender_send import main

if __name__ == "__main__":
    raise SystemExit(main())
