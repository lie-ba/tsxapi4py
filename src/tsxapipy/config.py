# tsxapipy/config.py
import os
import logging
from typing import Any, Optional # List removed as it was unused in this file

from dotenv import load_dotenv, find_dotenv

# Import ConfigurationError locally when needed to break circular dependency
# from tsxapipy.api.exceptions import ConfigurationError # No, do this inside functions/checks

logger = logging.getLogger(__name__) # CORRECT: Get logger, do not configure

# --- .env loading ---
project_root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
explicit_env_path = os.path.join(project_root_path, '.env')

logger.debug("Config: Attempting to load .env from explicit path: %s", explicit_env_path)

dotenv_path_to_load: Optional[str] = None
if os.path.exists(explicit_env_path):
    dotenv_path_to_load = explicit_env_path
else:
    logger.debug(
        "Config: Explicit .env path '%s' not found. Using find_dotenv default search.",
        explicit_env_path
    )
    try:
        found_path = find_dotenv(usecwd=True, raise_error_if_not_found=False)
        if found_path and os.path.exists(found_path):
            dotenv_path_to_load = found_path
    except Exception as e: # pylint: disable=broad-except
        logger.warning("Config: Error during find_dotenv: %s. Will proceed without .env if not found.", e)


if dotenv_path_to_load:
    logger.info("Config: Attempting to load environment variables from: %s", dotenv_path_to_load)
    loaded_successfully = load_dotenv(dotenv_path=dotenv_path_to_load, override=True)
    if loaded_successfully:
        logger.info("Config: Successfully loaded environment variables from: %s", dotenv_path_to_load)
    else:
        logger.warning(
            "Config: python-dotenv reported no variables loaded from %s, "
            "though the file was targeted. Check file content or permissions.",
            dotenv_path_to_load
        )
else:
    logger.warning(
        "Config: No .env file found at project root or standard locations. "
        "Relying on pre-existing system environment variables if any."
    )


# --- Define URL Sets ---
URL_SETS = {
    "LIVE": {
        "api": "https://api.toponefutures.projectx.com",
        "market_hub": "https://rtc.toponefutures.projectx.com/hubs/market",
        "user_hub": "https://rtc.toponefutures.projectx.com/hubs/user",
    },
    "DEMO": {
        "api": "https://gateway-api-demo.s2f.projectx.com",
        "market_hub": "https://gateway-rtc-demo.s2f.projectx.com/hubs/market",
        "user_hub": "https://gateway-rtc-demo.s2f.projectx.com/hubs/user",
    }
}

# --- Environment Selection ---
TRADING_ENV_SETTING = os.getenv("TRADING_ENVIRONMENT", "DEMO").upper()
if TRADING_ENV_SETTING not in URL_SETS:
    logger.warning(
        "Config: Invalid TRADING_ENVIRONMENT '%s' found in environment. "
        "Defaulting to 'DEMO'. Valid options are: %s",
        TRADING_ENV_SETTING,
        list(URL_SETS.keys())
    )
    TRADING_ENV_SETTING = "DEMO"
# Logging of TRADING_ENV_SETTING moved after credential checks to avoid premature exit issue
selected_urls = URL_SETS[TRADING_ENV_SETTING]

# --- Core API credentials ---
API_KEY = os.getenv("API_KEY")
USERNAME = os.getenv("USERNAME")

# --- Modified Config Check: Warn instead of raising error immediately ---
# The authenticate() function will now be responsible for raising ConfigurationError
# if credentials are not provided either as arguments or found in these config vars.
if not API_KEY:
    # pylint: disable=import-outside-toplevel
    # from tsxapipy.api.exceptions import ConfigurationError # Error raising moved to authenticate()
    msg = (
        "Config WARNING: API_KEY is not set in .env file or environment variables. "
        "Authentication will fail unless API_KEY is provided programmatically to authenticate()."
    )
    logger.warning(msg)
    # raise ConfigurationError(msg) # Removed raise

if not USERNAME:
    # pylint: disable=import-outside-toplevel
    # from tsxapipy.api.exceptions import ConfigurationError # Error raising moved to authenticate()
    msg = (
        "Config WARNING: USERNAME is not set in .env file or environment variables. "
        "Authentication will fail unless USERNAME is provided programmatically to authenticate()."
    )
    logger.warning(msg)
    # raise ConfigurationError(msg) # Removed raise

# Now log the active environment
logger.info("Config: TRADING_ENVIRONMENT active: '%s'.", TRADING_ENV_SETTING)


# --- Final Endpoint URLs (allowing overrides) ---
API_URL = os.getenv("API_BASE_URL_OVERRIDE_ENV") or selected_urls["api"]
MARKET_HUB_URL = os.getenv("MARKET_HUB_URL_OVERRIDE_ENV") or selected_urls["market_hub"]
USER_HUB_URL = os.getenv("USER_HUB_URL_OVERRIDE_ENV") or selected_urls["user_hub"]

# --- Other Optional Configurations ---
CONTRACT_ID = os.getenv("CONTRACT_ID")

ACCOUNT_ID_TO_WATCH_STR = os.getenv("ACCOUNT_ID_TO_WATCH")
ACCOUNT_ID_TO_WATCH: Optional[int] = None
if ACCOUNT_ID_TO_WATCH_STR and ACCOUNT_ID_TO_WATCH_STR.strip():
    try:
        ACCOUNT_ID_TO_WATCH = int(ACCOUNT_ID_TO_WATCH_STR)
        logger.debug(
            "Config: Converted ACCOUNT_ID_TO_WATCH to integer: %s",
            ACCOUNT_ID_TO_WATCH
        )
    except ValueError:
        logger.warning(
            "Config: ACCOUNT_ID_TO_WATCH ('%s') from env is not a valid integer. Setting to None.",
            ACCOUNT_ID_TO_WATCH_STR
        )
else:
    logger.debug(
        "Config: ACCOUNT_ID_TO_WATCH not found, empty, or whitespace in environment variables."
    )


# --- Token Management Configuration ---
TOKEN_EXPIRY_SAFETY_MARGIN_MINUTES = int(os.getenv("TOKEN_EXPIRY_SAFETY_MARGIN_MINUTES", "30"))
DEFAULT_TOKEN_LIFETIME_HOURS = float(os.getenv("DEFAULT_TOKEN_LIFETIME_HOURS", "23.5"))


# --- Logging of final effective configuration values ---
def _log_config_var(var_name: str, var_value: Any,
                    is_sensitive: bool = False, is_url: bool = False):
    """
    Helper function to log configuration variables, obscuring sensitive ones.

    Args:
        var_name (str): The name of the configuration variable.
        var_value (Any): The value of the configuration variable.
        is_sensitive (bool, optional): If True, the value will be obscured in logs.
                                       Defaults to False.
        is_url (bool, optional): If True, logs at INFO level, otherwise DEBUG
                                 (unless TRADING_ENV_SETTING). Defaults to False.
    """
    if var_value is not None:
        val_str = str(var_value)
        display_value = val_str
        if is_sensitive:
            if len(val_str) > 4:
                display_value = f"{'*' * (len(val_str) - 4)}{val_str[-4:]}"
            else:
                display_value = "***"
        log_level = logging.INFO if is_url or var_name in ["TRADING_ENV_SETTING"] else logging.DEBUG
        logger.log(log_level, "Config: Effective %s: %s", var_name, display_value)
    else:
        logger.debug("Config: %s is not set or resolved to None.", var_name)

logger.info("--- Effective Runtime Configuration ---")
_log_config_var("TRADING_ENV_SETTING", TRADING_ENV_SETTING)
_log_config_var("API_KEY", API_KEY, is_sensitive=True) # Kept original logging for these
_log_config_var("USERNAME", USERNAME)                 # as they still represent the config-loaded values
_log_config_var("API_URL", API_URL, is_url=True)
_log_config_var("MARKET_HUB_URL", MARKET_HUB_URL, is_url=True)
_log_config_var("USER_HUB_URL", USER_HUB_URL, is_url=True)
_log_config_var("CONTRACT_ID (default)", CONTRACT_ID)
_log_config_var("ACCOUNT_ID_TO_WATCH (default)", ACCOUNT_ID_TO_WATCH)
_log_config_var("TOKEN_EXPIRY_SAFETY_MARGIN_MINUTES", TOKEN_EXPIRY_SAFETY_MARGIN_MINUTES)
_log_config_var("DEFAULT_TOKEN_LIFETIME_HOURS", DEFAULT_TOKEN_LIFETIME_HOURS)
logger.info("--- End of Effective Runtime Configuration ---")


# --- Contextual Warnings for Optional Variables ---
if not CONTRACT_ID:
    logger.debug(
        "Config: Optional default CONTRACT_ID is not set. "
        "Scripts needing it may require CLI arg or will fail if it's mandatory for them."
    )
if ACCOUNT_ID_TO_WATCH is None:
    logger.debug(
        "Config: Optional default ACCOUNT_ID_TO_WATCH is not set or was invalid. "
        "Scripts needing it may require CLI arg or will fail if it's mandatory for them."
    )

# API configuration
API_BASE_URL = "https://api.tsxapi.com"  # Default API base URL
