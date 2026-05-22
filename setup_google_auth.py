"""
One-time Google OAuth2 setup script.
Run this ONCE to authorise Maya to access your Google Calendar:

    uv run setup_google_auth.py

It will open a browser, ask you to log in, and save google_token.json.
After that the agent will use the saved token (auto-refreshed).
"""

import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TOKEN_FILE = "google_token.json"

PORT = 8080

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

# Try "installed" (Desktop app) first; fall back to "web" if that's what the user created
CLIENT_CONFIG_INSTALLED = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [f"http://localhost:{PORT}", "http://localhost"],
    }
}

CLIENT_CONFIG_WEB = {
    "web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [f"http://localhost:{PORT}"],
    }
}


def main():
    if not CLIENT_ID:
        print("ERROR: GOOGLE_CLIENT_ID not set in .env")
        return

    print("=" * 60)
    print("Google Calendar Authorisation")
    print("=" * 60)
    print()
    print("IMPORTANT — Before continuing, make sure one of these is done:")
    print(f"  Option A: Your OAuth client type is 'Desktop app' in Google Cloud Console")
    print(f"  Option B: You added  http://localhost:{PORT}  as an Authorized Redirect URI")
    print(f"            for your Web application OAuth client in Google Cloud Console.")
    print()
    print("Opening browser... Please log in with the Google account")
    print("that owns the calendar you want Maya to use.")
    print()

    # Try installed app flow first, then web flow
    for config_key, config_data in [
        ("installed", CLIENT_CONFIG_INSTALLED),
        ("web", CLIENT_CONFIG_WEB),
    ]:
        try:
            flow = InstalledAppFlow.from_client_config(config_data, SCOPES)
            creds = flow.run_local_server(port=PORT, open_browser=True)
            break
        except Exception as e:
            if config_key == "web":
                print(f"ERROR: Could not complete auth flow: {e}")
                print()
                print("Please check that:")
                print(f"  1. http://localhost:{PORT} is added as Authorized Redirect URI in Google Cloud Console")
                print("  2. The Google Calendar API is enabled in your project")
                return

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"\nSuccess! Token saved to {TOKEN_FILE}")
    print("Maya can now access your Google Calendar.")
    print()
    print("Add your calendar ID to .env:")
    print("  GOOGLE_CALENDAR_ID=your.email@gmail.com   (or the calendar ID from Google Calendar settings)")


if __name__ == "__main__":
    main()
