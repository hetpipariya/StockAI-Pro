import requests

CODE = "8pWlSm"

API_KEY = "537c438b-d56b-4295-b65e-6b47159b3ca3"
API_SECRET = "0yvaiafj1j"
REDIRECT_URI = "http://127.0.0.1:8000/callback"

url = "https://api.upstox.com/v2/login/authorization/token"

payload = {
    "code": CODE,
    "client_id": API_KEY,
    "client_secret": API_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code"
}

headers = {
    "accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded"
}

response = requests.post(url, data=payload, headers=headers)

print(response.json())