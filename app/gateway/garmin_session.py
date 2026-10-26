"""Garmin login using tokens stored in SSM Parameter Store (never a password).

Flow: SSM SecureString -> /tmp token file -> garminconnect login (auto-refreshes the
access token) -> if the token file changed, write it back to SSM so the next
invocation starts with the fresh token.
"""

import logging
import os

import boto3

log = logging.getLogger(__name__)

TOKEN_DIR = "/tmp/garmin-tokens"
TOKEN_FILE = os.path.join(TOKEN_DIR, "garmin_tokens.json")


class NotBootstrappedError(RuntimeError):
    pass


class GarminSession:
    def __init__(self, param_name: str | None = None):
        self.param = param_name or os.environ["GARMIN_TOKENS_PARAM"]
        self.ssm = boto3.client("ssm")
        self._last_saved: str | None = None

    def __enter__(self):
        value = self.ssm.get_parameter(Name=self.param, WithDecryption=True)["Parameter"]["Value"]
        if value.startswith("PLACEHOLDER"):
            raise NotBootstrappedError(
                "Garmin tokens are not set yet. Run scripts/bootstrap_garmin_auth.py on your computer."
            )
        os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(value)
        os.chmod(TOKEN_FILE, 0o600)
        self._last_saved = value

        from garminconnect import Garmin

        client = Garmin()  # no credentials: tokens only, so an expired session fails loudly
        client.login(TOKEN_DIR)
        self.persist()  # login may already have refreshed the access token
        return client

    def persist(self) -> None:
        try:
            with open(TOKEN_FILE) as f:
                current = f.read()
        except FileNotFoundError:
            return
        if current and current != self._last_saved:
            self.ssm.put_parameter(
                Name=self.param, Value=current, Type="SecureString", Overwrite=True, Tier="Intelligent-Tiering"
            )
            self._last_saved = current
            log.info("Persisted refreshed Garmin tokens to SSM")

    def __exit__(self, *exc):
        try:
            self.persist()
        except Exception:
            log.exception("Failed to persist refreshed Garmin tokens")
        return False


def is_auth_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "authentication" in text or "401" in text or "unauthorized" in text
