"""
Shonya API Authentication Module
Handles authentication to the Shoonya (Finvasia) Noren REST API via GenAcsTok.

Reference: https://shoonya.com/api-documentation
Endpoint:  /NorenWClientAPI/GenAcsTok

Login POST format:
  - Content-Type: application/x-www-form-urlencoded
  - Body: jData=<JSON string>

Fields:
  - code     : OAuth auth code obtained via browser login (get_authcode.py)
  - checksum : sha256(vendor_code + secret_code + oauth_code), no separators

.env variables:
  SHOONYA_API_HOST     - Base API URL, e.g. https://api.shoonya.com/NorenWClientAPI
  SHONYA_VENDOR_CODE   - Vendor/app key from the Shoonya portal (also used as api_key in OAuth URL)
  SHONYA_API_SECRET   - Secret key from the Shoonya portal
  SHONYA_USER_ID       - Shoonya user ID for browser login
  SHONYA_PASSWORD      - Shoonya account password for browser login
  SHONYA_TWO_FA        - TOTP secret key (used during browser login)
"""

import os
import json
import hashlib
import requests
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from get_authcode import get_auth_code

load_dotenv()

SHOONYA_API_HOST = os.getenv("SHOONYA_API_HOST")

_TOKEN_STORE_PATH = Path(__file__).parent / "token_store.json"


def _load_token_store() -> dict:
    if _TOKEN_STORE_PATH.exists():
        try:
            return json.loads(_TOKEN_STORE_PATH.read_text()) or {}
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_token_store(data: dict) -> None:
    _TOKEN_STORE_PATH.write_text(json.dumps(data, indent=2))


def _issued_today(timestamp_str: Optional[str]) -> bool:
    if not timestamp_str:
        return False
    try:
        return datetime.fromisoformat(timestamp_str).date() == date.today()
    except (ValueError, TypeError):
        return False


class ShonyaAuthenticator:
    """Handles authentication with the Shoonya (Finvasia) Noren REST API."""

    def __init__(self):
        """Initialize authenticator with credentials from environment variables."""
        self.vendor_code = os.getenv("SHONYA_VENDOR_CODE")
        self.secret_code = os.getenv("SHONYA_API_SECRET")

        self.auth_token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.session: Optional[requests.Session] = None

        self._validate_credentials()

    def _validate_credentials(self) -> None:
        """Validate that all required credentials are present."""
        required = {
            "SHONYA_VENDOR_CODE": self.vendor_code,
            "SHONYA_API_SECRET": self.secret_code,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(
                f"Missing required Shoonya API credentials: {', '.join(missing)}. "
                "Please set them in your .env file."
            )

    @staticmethod
    def _sha256(value: str) -> str:
        """Return the SHA-256 hex digest of a string."""
        return hashlib.sha256(value.encode()).hexdigest()

    def authenticate(self, api_url: str = SHOONYA_API_HOST) -> Dict[str, Any]:
        """
        Authenticate with the Shoonya Noren REST API via GenAcsTok.

        Obtains an OAuth auth code via browser login (get_authcode), then computes:
          checksum = sha256(vendor_code + secret_code + oauth_code)

        Args:
            api_url: Base URL of the Shoonya API (defaults to SHOONYA_API_HOST).

        Returns:
            Dict with keys: success (bool), message (str), token (str|None),
            response (dict).
        """
        try:
            store = _load_token_store()

            # Reuse a valid session token from today — skip browser login entirely.
            if store.get("susertoken") and _issued_today(store.get("susertoken_issued_at")):
                self.auth_token = store["susertoken"]
                self.user_id = store.get("user_id")
                self.session = requests.Session()
                self.session.headers.update({
                    "jKey": self.auth_token,
                    "Content-Type": "application/x-www-form-urlencoded",
                })
                return {
                    "success": True,
                    "message": "Using cached Shoonya session token",
                    "token": self.auth_token,
                    "response": {},
                }

            # Reuse a cached OAuth code from today; otherwise open the browser.
            oauth_code: Optional[str] = None
            if store.get("oauth_code") and _issued_today(store.get("oauth_code_issued_at")):
                oauth_code = store["oauth_code"]

            if not oauth_code:
                oauth_code = get_auth_code()
                store["oauth_code"] = oauth_code
                store["oauth_code_issued_at"] = datetime.now().isoformat()
                _save_token_store(store)

            checksum = self._sha256(f"{self.vendor_code}{self.secret_code}{oauth_code}")

            payload = {
                "code": oauth_code,
                "checksum": checksum,
            }

            base_url = api_url.rstrip("/")
            auth_endpoint = f"{base_url}/GenAcsTok"

            self.session = requests.Session()

            post_data = f"jData={json.dumps(payload)}"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            response = self.session.post(
                auth_endpoint,
                data=post_data,
                headers=headers,
                timeout=30,
                verify=True,
            )
            response.raise_for_status()

            auth_response = response.json()

            if auth_response.get("stat") == "Ok":
                self.auth_token = auth_response.get("susertoken")
                self.user_id = auth_response.get("uid")

                if self.auth_token:
                    self.session.headers.update({
                        "jKey": self.auth_token,
                        "Content-Type": "application/x-www-form-urlencoded",
                    })
                    store["susertoken"] = self.auth_token
                    store["susertoken_issued_at"] = datetime.now().isoformat()
                    store["user_id"] = self.user_id
                    _save_token_store(store)

                return {
                    "success": True,
                    "message": "Successfully authenticated with Shoonya API",
                    "token": self.auth_token,
                    "response": auth_response,
                }
            else:
                # Cached OAuth code may have been consumed — clear it so the next
                # call goes through a fresh browser login.
                if "oauth_code" in store:
                    store.pop("oauth_code", None)
                    store.pop("oauth_code_issued_at", None)
                    _save_token_store(store)

                error_msg = auth_response.get("emsg", "Unknown error from API")
                return {
                    "success": False,
                    "message": f"Authentication failed: {error_msg}",
                    "token": None,
                    "response": auth_response,
                }

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status >= 500:
                return {
                    "success": False,
                    "message": (
                        f"Shoonya GenAcsTok returned HTTP {status} — the server appears to be down. "
                        "Try again in a few minutes. "
                        f"Endpoint: {api_url.rstrip('/')}/GenAcsTok"
                    ),
                    "token": None,
                    "error": str(e),
                }
            return {
                "success": False,
                "message": f"Authentication failed with HTTP {status}: {str(e)}",
                "token": None,
                "error": str(e),
            }

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            return {
                "success": False,
                "message": (
                    f"Could not reach Shoonya API at {api_url}: {e}. "
                    "Check network connectivity and try again."
                ),
                "token": None,
                "error": str(e),
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "message": f"Request error during authentication: {str(e)}",
                "token": None,
                "error": str(e),
            }

    def get_session(self) -> requests.Session:
        """
        Return the authenticated session for making subsequent API requests.

        Raises:
            RuntimeError: If authenticate() has not been called successfully.
        """
        if not self.auth_token or not self.session:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        return self.session

    def is_authenticated(self) -> bool:
        """Return True if a valid session token is held."""
        return self.auth_token is not None


def get_authenticated_session(api_url: str = SHOONYA_API_HOST) -> requests.Session:
    """
    Convenience function: authenticate and return a ready-to-use session.

    Args:
        api_url: Base URL of the Shoonya API.

    Returns:
        Authenticated requests.Session with jKey header set.

    Raises:
        ValueError: If any required credential is missing from the environment.
        RuntimeError: If authentication fails.
    """
    authenticator = ShonyaAuthenticator()
    result = authenticator.authenticate(api_url)

    if not result["success"]:
        raise RuntimeError(result["message"])

    return authenticator.get_session()


if __name__ == "__main__":
    try:
        auth = ShonyaAuthenticator()
        print("Credentials loaded successfully")

        print(f"\nAttempting authentication via {SHOONYA_API_HOST}/GenAcsTok ...")
        result = auth.authenticate()

        if result["success"]:
            token = result["token"]
            print(f"Auth successful: {result['message']}")
            print(f"Token: {token[:20]}..." if token else "No token received")
        else:
            print(f"Auth failed: {result['message']}")
            print(f"API response: {result.get('response', {})}")
            if "error" in result:
                print(f"Error details: {result['error']}")

    except ValueError as e:
        print(f"Configuration Error: {e}")
    except Exception as e:
        print(f"Unexpected Error: {e}")
