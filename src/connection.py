"""WRDS connection with credential lookup, retry, and context manager."""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Generator

if os.name == "nt":
    import winreg

import wrds


def get_env_credential(name: str) -> str | None:
    """Return credential from process env, then Windows user-env registry as fallback."""
    value = os.getenv(name)
    if value:
        return value
    if os.name != "nt":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            reg_value, _ = winreg.QueryValueEx(key, name)
            if isinstance(reg_value, str) and reg_value.strip():
                return reg_value.strip()
    except OSError:
        pass
    return None


def connect(username: str | None = None, password: str | None = None, max_retries: int = 3) -> wrds.Connection:
    """Open a WRDS connection with exponential-backoff retry."""
    import builtins
    import getpass
    import re

    username = username or get_env_credential("WRDS_USERNAME")
    password = password or get_env_credential("WRDS_PASSWORD")

    kwargs: dict = {}
    if username:
        kwargs["wrds_username"] = username
    if password:
        kwargs["wrds_password"] = password

    # The wrds library calls input() and getpass.getpass() interactively even
    # when credentials are passed as kwargs.  Patch both so the pipeline
    # runs non-interactively when credentials are available.
    _orig_input    = builtins.input
    _orig_getpass  = getpass.getpass

    def _silent_input(prompt: str = "") -> str:
        pl = prompt.lower()
        if username and "username" in pl:
            m = re.search(r"\[([^\]]+)\]", prompt)
            return m.group(1) if m else username
        if "pgpass" in pl and "[y/n]" in pl:
            print(f"  Auto-answering pgpass prompt: y")
            return "y"
        return _orig_input(prompt)

    def _silent_getpass(prompt: str = "Password: ", stream=None) -> str:
        if password and ("password" in prompt.lower() or "wrds" in prompt.lower()):
            return password
        return _orig_getpass(prompt, stream)

    builtins.input   = _silent_input
    getpass.getpass  = _silent_getpass

    last_exc: Exception | None = None
    try:
        for attempt in range(1, max_retries + 1):
            try:
                print(f"Connecting to WRDS (attempt {attempt}/{max_retries})...")
                conn = wrds.Connection(**kwargs)
                print("  Connected.")
                return conn
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = 2 ** attempt
                    print(f"  Failed: {exc}. Retrying in {wait}s...")
                    time.sleep(wait)
    finally:
        builtins.input  = _orig_input
        getpass.getpass = _orig_getpass

    print(f"ERROR: Could not connect to WRDS after {max_retries} attempts: {last_exc}", file=sys.stderr)
    sys.exit(1)


@contextmanager
def wrds_connection(username: str | None = None, password: str | None = None) -> Generator[wrds.Connection, None, None]:
    """Context manager: open WRDS connection, guarantee close on exit."""
    conn = connect(username=username, password=password)
    try:
        yield conn
    finally:
        conn.close()
