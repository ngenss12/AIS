import json
import os
import httpx
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

GFW_TOKEN = os.environ["GFW_TOKEN"]

GFW_BASE = "https://gateway.api.globalfishingwatch.org/v3"
INDONESIA_POLY = {
    "type": "Polygon",
    "coordinates": [[[95.0, -11.0], [141.0, -11.0], [141.0, 6.0], [95.0, 6.0], [95.0, -11.0]]],
}
GFW_DATASETS = [
    "public-global-fishing-events:latest",
    "public-global-encounters-events:latest",
    "public-global-loitering-events:latest",
]


def fetch_events(days: int = 7) -> list:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    result = []
    with httpx.Client(timeout=25) as client:
        resp = client.post(
            f"{GFW_BASE}/events",
            headers={"Authorization": f"Bearer {GFW_TOKEN}", "Content-Type": "application/json"},
            params={"limit": 200, "offset": 0, "sort": "-start"},
            json={
                "datasets":  GFW_DATASETS,
                "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDate":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "geometry":  INDONESIA_POLY,
            },
        )
        resp.raise_for_status()
        for entry in resp.json().get("entries", []):
            pos    = entry.get("position", {})
            vessel = entry.get("vessel", {})
            lat, lon = pos.get("lat"), pos.get("lon")
            if not lat or not lon:
                continue
            result.append({
                "source":       "gfw",
                "event_type":   (entry.get("type") or "UNKNOWN").upper(),
                "event_id":     entry.get("id"),
                "mmsi":         vessel.get("ssvid"),
                "ship_name":    (vessel.get("name") or "Unknown").strip() or "Unknown",
                "flag":         vessel.get("flag"),
                "lat": lat, "lon": lon,
                "waktu":        entry.get("start"),
                "end":          entry.get("end"),
                "duration_min": entry.get("durationInMinutes"),
            })
    return result


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            qs   = parse_qs(urlparse(self.path).query)
            days = int(qs.get("days", ["7"])[0])
            days = max(1, min(days, 30))
            body = json.dumps(fetch_events(days)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        pass
