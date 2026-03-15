import httpx
import json

URL = "https://thredion-production.up.railway.app"

try:
    print(f"Checking {URL}/health")
    r = httpx.get(f"{URL}/health")
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(e)
