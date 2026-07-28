"""
Overpass API scraper: pulls all traffic signal nodes within Bengaluru's
administrative boundary and writes them to signal.json.
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse

OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"
OUTPUT_FILE = "signal.json"

# area["name"="Bengaluru"] resolves to the official admin boundary relation
# in OSM, avoiding the need to hardcode a bbox (which misses signals near edges).
QUERY = """
[out:json][timeout:180];
area["name"="Bengaluru"]["boundary"="administrative"]->.searchArea;
(
  node["highway"="traffic_signals"](area.searchArea);
);
out body;
"""


def fetch_signals(retries: int = 3, backoff: int = 10) -> dict:
    data = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
    req = urllib.request.Request(OVERPASS_URL, data=data)

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=200) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff)
            else:
                raise


def main():
    raw = fetch_signals()
    elements = raw.get("elements", [])

    signals = [
        {
            "id": el["id"],
            "lat": el["lat"],
            "lon": el["lon"],
            "tags": el.get("tags", {}),
        }
        for el in elements
        if el.get("type") == "node"
    ]

    with open(OUTPUT_FILE, "w") as f:
        json.dump(signals, f, indent=2)

    print(f"Fetched {len(signals)} traffic signal nodes -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()