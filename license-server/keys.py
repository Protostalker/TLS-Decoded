"""
No longer used.

The license server originally signed Unlimited license files as JWTs
(RSA-signed, verified offline by the Cloud Utility). That's been replaced
by a much simpler design per Raffi's call: everything is a passphrase
looked up in a database, and every Cloud Utility always phones home to
check it — no signing keys, no offline verification, no JWT files. See
models.py and main.py's module docstrings for the current design.

Kept as an empty file (rather than deleted) only because this sandbox
can't unlink it — safe to delete by hand; nothing imports this module
anymore.
"""
