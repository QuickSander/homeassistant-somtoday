"""Constants for the SomToday integration.

This module is deliberately free of Home Assistant imports so that the
authentication layer can be unit tested without the Home Assistant runtime.
The constant set follows ``docs/architecture.md`` section 10.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "sometoday"

# ---------------------------------------------------------------------------
# Config entry data keys
# ---------------------------------------------------------------------------
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_API_URL: Final = "api_url"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_STUDENT_ID: Final = "student_id"
CONF_STUDENT_NAME: Final = "student_name"

# Transient config-flow field holding the pasted redirect URL / code. Never
# persisted in the config entry.
CONF_REDIRECT_URL: Final = "redirect_url"

# Config entry option keys
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_SCHEDULE_DAYS_AHEAD: Final = "schedule_days_ahead"
CONF_HOMEWORK_DAYS_AHEAD: Final = "homework_days_ahead"
CONF_ENABLE_GRADES: Final = "enable_grades"
CONF_ENABLE_HOMEWORK: Final = "enable_homework"
CONF_ENABLE_ABSENCE: Final = "enable_absence"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SCAN_INTERVAL: Final = 15  # minutes
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 1440
DEFAULT_SCHEDULE_DAYS_AHEAD: Final = 14
DEFAULT_HOMEWORK_DAYS_AHEAD: Final = 7
DEFAULT_API_URL: Final = "https://api.somtoday.nl"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
# Public OAuth2 client. No client secret is used: PKCE replaces it, and the
# authorize request deliberately omits ``tenant_uuid`` so SomToday shows its
# own school picker.
CLIENT_ID_APP: Final = "somtoday-leerling-native"

AUTHORIZE_URL: Final = "https://inloggen.somtoday.nl/oauth2/authorize"
TOKEN_URL: Final = "https://inloggen.somtoday.nl/oauth2/token"
REDIRECT_URI: Final = "somtoday://nl.topicus.somtoday.leerling/oauth/callback"

SCOPE: Final = "openid"
SESSION_NO_SESSION: Final = "no_session"
TOKEN_REFRESH_MARGIN: Final = 120  # seconds before expiry to refresh

# PKCE
CODE_VERIFIER_LENGTH: Final = 128
# The SomToday app uses lowercase letters and digits (without zero). This is a
# subset of the RFC 7636 unreserved set ``[A-Za-z0-9-._~]``.
PKCE_CHARSET: Final = "abcdefghijklmnopqrstuvwxyz123456789"
STATE_LENGTH: Final = 32

# HTTP
REQUEST_TIMEOUT: Final = 30  # seconds
