"""Constants for the SomToday integration.

This module is deliberately free of Home Assistant imports so that the
authentication layer can be unit tested without the Home Assistant runtime.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "sometoday"

# ---------------------------------------------------------------------------
# Config entry data keys
# ---------------------------------------------------------------------------
CONF_TENANT_UUID: Final = "tenant_uuid"
CONF_SCHOOL_NAME: Final = "school_name"
CONF_USERNAME: Final = "username"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_API_URL: Final = "api_url"
CONF_STUDENT_ID: Final = "student_id"
CONF_STUDENT_NAME: Final = "student_name"
CONF_AUTH_METHOD: Final = "auth_method"

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
AUTH_METHOD_PKCE: Final = "pkce"
AUTH_METHOD_PASSWORD: Final = "password"

# Public OAuth2 clients. No client secret is used: PKCE replaces it.
CLIENT_ID_APP: Final = "somtoday-leerling-native"
CLIENT_ID_SSO: Final = "D50E0C06-32D1-4B41-A137-A9A850C892C2"

AUTHORIZE_URL: Final = "https://inloggen.somtoday.nl/oauth2/authorize"
TOKEN_URL: Final = "https://inloggen.somtoday.nl/oauth2/token"
TOKEN_URL_SSO: Final = "https://somtoday.nl/oauth2/token"
SCHOOLS_URL: Final = "https://servers.somtoday.nl/organisaties.json"
LOGIN_BASE_URL: Final = "https://inloggen.somtoday.nl"
REDIRECT_URI: Final = "somtoday://nl.topicus.somtoday.leerling/oauth/callback"

SCOPE: Final = "openid"
SESSION_NO_SESSION: Final = "no_session"
TOKEN_REFRESH_MARGIN: Final = 120  # seconds before expiry to refresh

# HTML form field names used by the SomToday login page.
USERNAME_FIELD: Final = "usernameFieldPanel:usernameFieldPanel_body:usernameField"
PASSWORD_FIELD: Final = "passwordFieldPanel:passwordFieldPanel_body:passwordField"

# PKCE
CODE_VERIFIER_LENGTH: Final = 128
# The SomToday app uses lowercase letters and digits (without zero).
PKCE_CHARSET: Final = "abcdefghijklmnopqrstuvwxyz123456789"
STATE_LENGTH: Final = 8

# HTTP
REQUEST_TIMEOUT: Final = 30  # seconds
