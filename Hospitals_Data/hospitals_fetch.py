import requests
import json
import time

MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",  # last resort
]

HEADERS = {
    "User-Agent": "AmbulanceRoutingHackathon/1.0 (student project, contact: chandanmurthy05@gmail.com)",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate",
}

QUERY = """
[out:json][timeout:90];
area["name"="Bengaluru"]["boundary"="administrative"]->.searchArea;
(
  node["amenity"~"hospital|clinic"](area.searchArea);
  way["amenity"~"hospital|clinic"](area.searchArea);
);
out center tags;
"""

def fetch_raw_data():
    for url in MIRRORS:
        print(f"Trying {url} ...")
        try:
            response = requests.post(url, data={"data": QUERY}, headers=HEADERS, timeout=100)
            if response.status_code == 200:
                data = response.json()
                print(f"Success via {url} — fetched {len(data['elements'])} elements")
                return data
            else:
                print(f"  Got {response.status_code}, trying next mirror...")
        except requests.exceptions.RequestException as e:
            print(f"  Failed: {e}, trying next mirror...")
        time.sleep(2)
    raise RuntimeError("All Overpass mirrors failed. Try again in a few minutes.")

if __name__ == "__main__":
    data = fetch_raw_data()
    with open("raw_hospitals.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("Saved to raw_hospitals.json")