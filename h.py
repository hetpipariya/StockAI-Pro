import webbrowser
from urllib.parse import quote

API_KEY = "537c438b-d56b-4295-b65e-6b47159b3ca3"
REDIRECT_URI = "http://127.0.0.1:8000/callback"

login_url = (
    "https://api.upstox.com/v2/login/authorization/dialog"
    "?response_type=code"
    f"&client_id={API_KEY}"
    f"&redirect_uri={quote(REDIRECT_URI)}"
)

print(login_url)

webbrowser.open(login_url)