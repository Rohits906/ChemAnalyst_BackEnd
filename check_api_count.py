import requests
import json

# Using the local dev server URL
url = "http://127.0.0.1:8000/api/sentiment/my-sentiments/?all=true"

try:
    response = requests.get(url)
    data = response.json()
    if data.get("success"):
        count = data.get("count")
        results_len = len(data.get("results", []))
        print(f"API Reported Count: {count}")
        print(f"Actual Records in Results: {results_len}")
    else:
        print(f"API Error: {data}")
except Exception as e:
    print(f"Connection Error: {e}")
