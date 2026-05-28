import requests

TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1RUNWUjMiLCJqdGkiOiI2YTBlYzkxYTEzZjAyMTAyY2FkZmQwY2IiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3OTM1Mzg4MiwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzc5NDAwODAwfQ.qmk1zFKb-aclag0d4otaH0oDgvNok2YynnkxJaFVVgs"

headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

response = requests.get(
    "https://api.upstox.com/v2/user/profile",
    headers=headers
)

print(response.status_code)
print(response.text)