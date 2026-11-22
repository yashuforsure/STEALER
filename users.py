"""users.py - compatibility shim.

Sender identity is PC-wise now (hostname/user/MAC/public IP), not browser
profile wise. Import senders directly in new code.
"""

from senders import choose, discover, records_for, table  # noqa: F401
