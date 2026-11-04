"""Round 21 (D100): keep the secret Offline link token out of the app's log lines."""
import logging
import re

TOKEN_PATH_RE = re.compile(r"(/offline/)[^/\s]+")


def redact(text):
    return TOKEN_PATH_RE.sub(r"\1<token>", text)


class RedactOfflineToken(logging.Filter):
    """Django's request logger writes the full path of 4xx responses, which holds the token of an Offline link.

    Replaces the token in the message and its arguments. (The web server's own access log is not touched by this.)
    """

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True
