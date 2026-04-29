import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

AIS_KEY   = "cadc1da33463ea00ff85c0c1d8506ce3b8a57fcd"
GFW_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImtpZEtleSJ9.eyJkYXRhIjp7Im5hbWUiOiJGaXNoaW5nIFZlc3NlbCBJbmRvbmVzaWEiLCJ1c2VySWQiOjYxMTk5LCJhcHBsaWNhdGlvbk5hbWUiOiJGaXNoaW5nIFZlc3NlbCBJbmRvbmVzaWEiLCJpZCI6MTA1MTIsInR5cGUiOiJ1c2VyLWFwcGxpY2F0aW9uIn0sImlhdCI6MTc3NzI4OTUzOCwiZXhwIjoyMDkyNjQ5NTM4LCJhdWQiOiJnZnciLCJpc3MiOiJnZncifQ.bE8bCkhc9HZIqktF-xW7fTSeCho2xyNdJD7e_mZFXBDIOUVubbkFgixDd5APg0XWWbWEA2bp5340pRkP5o4g8VdDUc4aE60AbZBQvWE1A-fgM7aTI-sbD0T7TvJ2PWkay1rE7nEOGZVsb7fyl1SVRQac0987-bmwSzwtvflJH9j08HGVQ4i29cl2op6vWAy02D9TY-DKrugYw4RO4O2jWeTL0wjS_FjUAaY0GnvQDelcySLIl084GI9_sJd2ZFP56X7gbATpwhOJSB0xD0XxnwMbSJNmJWEevX_cgcJg-FWhPfNW6udfTEgFOpwlla7VlH_6utIpwiwmynAJZI1jEQHeFbbTS-Fh2xjAJhR_eseUDouAl_i3tceZRAYcv16BdoI46e5does-QwUz16r2isJbCI0ry80lnYv3Lj6JGXqFVsIY9_GgEJQH1EfJZTqNFbpopGJeT20nsn_FBZgK2owSfo5jYSvKMu0UGrzj4sKheuQ2u9TzStGKevrdEDwM"

AIS_REGIONS = [
    [[-8.0, 105.0], [-4.0, 116.0]],
    [[1.0, 99.0],   [6.0, 104.0]],
    [[-8.0, 112.0], [-6.5, 113.5]],
]

INDONESIA_POLY = {
    "type": "Polygon",
    "coordinates": [[[95.0, -11.0], [141.0, -11.0], [141.0, 6.0], [95.0, 6.0], [95.0, -11.0]]],
}

GFW_DATASETS = [
    "public-global-fishing-events:latest",
    "public-global-encounters-events:latest",
    "public-global-loitering-events:latest",
]

GFW_BASE = "https://gateway.api.globalfishingwatch.org/v3"

clients: set[WebSocket] = set()
current_source: str = "aisstream"
current_gfw_days: int = 7
gfw_trigger = asyncio.Event()

HERE = Path(__file__).parent


# ---------- broadcast ----------

async def broadcast(data: dict):
    if not clients:
        return
    msg = json.dumps(data)
    dead = set()
    for client in clients.copy():
        try:
            await client.send_text(msg)
        except Exception:
            dead.add(client)
    clients.difference_update(dead)


# ---------- parsers ----------

def parse_ais(msg: dict) -> dict | None:
    msg_type = msg.get("MessageType")
    meta = msg.get("MetaData", {})
    lat = meta.get("latitude")
    lon = meta.get("longitude")
    if not lat or not lon:
        return None
    base = {
        "source":    "aisstream",
        "mmsi":      meta.get("MMSI"),
        "ship_name": (meta.get("ShipName") or "Unknown").strip(),
        "lat": lat, "lon": lon,
        "waktu":     meta.get("time_utc"),
        "speed": None, "course": None, "heading": None,
        "nav_status": None, "destination": None,
    }
    if msg_type == "PositionReport":
        pr = msg.get("Message", {}).get("PositionReport", {})
        base["speed"]      = pr.get("Sog")
        base["course"]     = pr.get("Cog")
        base["heading"]    = pr.get("TrueHeading")
        base["nav_status"] = pr.get("NavigationalStatus")
    elif msg_type == "ShipStaticData":
        sd = msg.get("Message", {}).get("ShipStaticData", {})
        base["destination"] = (sd.get("Destination") or "").strip()
    return base


def parse_gfw(entry: dict) -> dict | None:
    pos    = entry.get("position", {})
    vessel = entry.get("vessel", {})
    lat, lon = pos.get("lat"), pos.get("lon")
    if not lat or not lon:
        return None
    return {
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
        "speed": None, "course": None, "heading": None,
    }


# ---------- AISStream task ----------

async def ais_stream():
    uri = "wss://stream.aisstream.io/v0/stream"
    while True:
        if current_source != "aisstream":
            await asyncio.sleep(3)
            continue
        try:
            async with websockets.connect(
                uri, ping_interval=30, ping_timeout=60, close_timeout=10
            ) as ws:
                await ws.send(json.dumps({
                    "APIKey": AIS_KEY,
                    "BoundingBoxes": AIS_REGIONS,
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                }))
                print("✅ AISStream terhubung")
                async for raw in ws:
                    if current_source != "aisstream":
                        break
                    data = parse_ais(json.loads(raw))
                    if data:
                        await broadcast(data)
            print("⚠️  AISStream ditutup — reconnect...")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"⚠️  AISStream terputus ({e.code}) — reconnect 5s...")
        except Exception as e:
            print(f"❌ AISStream error: {type(e).__name__}: {e} — reconnect 5s...")
        await asyncio.sleep(5)


# ---------- GFW task ----------

async def gfw_fetch_page(offset: int, days: int, client: httpx.AsyncClient) -> dict:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    resp = await client.post(
        f"{GFW_BASE}/events",
        headers={"Authorization": f"Bearer {GFW_TOKEN}", "Content-Type": "application/json"},
        params={"limit": 200, "offset": offset, "sort": "-start"},
        json={
            "datasets":  GFW_DATASETS,
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDate":   end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geometry":  INDONESIA_POLY,
        },
    )
    resp.raise_for_status()
    return resp.json()


async def gfw_poll():
    while True:
        if current_source != "gfw":
            await asyncio.sleep(3)
            continue
        try:
            offset = 0
            total  = 0
            days   = current_gfw_days
            # satu AsyncClient dipakai ulang untuk semua halaman (koneksi lebih cepat)
            async with httpx.AsyncClient(timeout=30) as client:
                while total < 500:
                    page    = await gfw_fetch_page(offset, days, client)
                    entries = page.get("entries", [])

                    # broadcast halaman ini langsung — tidak perlu tunggu halaman berikutnya
                    count = 0
                    for entry in entries:
                        parsed = parse_gfw(entry)
                        if parsed:
                            await broadcast(parsed)
                            count += 1
                    total   += count
                    next_off = page.get("nextOffset")
                    print(f"  GFW halaman: {count} events (offset {offset})")
                    if not next_off:
                        break
                    offset = next_off

            print(f"✅ GFW selesai: {total} events ({days} hari)")
            await broadcast({"type": "gfw_done", "count": total})
        except httpx.HTTPStatusError as e:
            print(f"❌ GFW HTTP {e.response.status_code}: {e.response.text[:200]}")
        except Exception as e:
            print(f"❌ GFW error: {type(e).__name__}: {e}")

        gfw_trigger.clear()
        try:
            await asyncio.wait_for(gfw_trigger.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass


# ---------- FastAPI ----------

@asynccontextmanager
async def lifespan(_: FastAPI):
    t1 = asyncio.create_task(ais_stream())
    t2 = asyncio.create_task(gfw_poll())
    yield
    t1.cancel()
    t2.cancel()


app = FastAPI(lifespan=lifespan)


async def browser_keepalive(websocket: WebSocket):
    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except Exception:
        pass


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    await websocket.send_text(json.dumps({"type": "source", "source": current_source}))
    ping_task = asyncio.create_task(browser_keepalive(websocket))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        clients.discard(websocket)


@app.post("/api/gfw/days/{n}")
async def set_gfw_days(n: int):
    global current_gfw_days
    if n not in (1, 3, 7, 14, 30):
        return JSONResponse({"error": "invalid days"}, status_code=400)
    current_gfw_days = n
    print(f"🗓  GFW range diubah: {n} hari")
    if current_source == "gfw":
        gfw_trigger.set()
    return JSONResponse({"days": current_gfw_days})


@app.get("/api/source")
async def get_source():
    return JSONResponse({"source": current_source})


@app.post("/api/source/{src}")
async def set_source(src: str):
    global current_source
    if src not in ("aisstream", "gfw"):
        return JSONResponse({"error": "invalid source"}, status_code=400)
    current_source = src
    await broadcast({"type": "source", "source": current_source})
    print(f"🔄 Pindah ke sumber: {current_source}")
    if src == "gfw":
        gfw_trigger.set()
    return JSONResponse({"source": current_source})


@app.get("/")
async def index():
    return HTMLResponse((HERE / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
