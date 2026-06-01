import requests

TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1RUNWUjMiLCJqdGkiOiI2YTFhNzk1ZGE4NDA2YTA1NTc0ZWZmZTQiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4MDExOTkwMSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzgwMTc4NDAwfQ._CLZ6mgOhO3NI0pjrYOY1eOeAonJpr4WWm8zqu3SAxY', 'extended_token': 'eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1RUNWUjMiLCJqdGkiOiI2OWNkNDU0NmZkYzMwMTMxMTQ0ZGZhMWMiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc3NTA2MDI5NCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODA2NjE2ODAwfQ.270IrFQavyPGJqUpX9JDW_5_mlPLAa__NfYB46DnOB0"

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