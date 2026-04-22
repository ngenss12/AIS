import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

API_KEY = "cadc1da33463ea00ff85c0c1d8506ce3b8a57fcd"

REGIONS = [
    [[-8.0, 105.0], [-4.0, 116.0]],   # Laut Jawa
    [[1.0, 99.0],   [6.0, 104.0]],    # Selat Malaka
    [[-8.0, 112.0], [-6.5, 113.5]],   # Perairan Surabaya
]

clients: set[WebSocket] = set()


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


def parse(msg: dict) -> dict | None:
    msg_type = msg.get("MessageType")
    meta = msg.get("MetaData", {})

    lat = meta.get("latitude")
    lon = meta.get("longitude")
    if not lat or not lon:
        return None

    base = {
        "mmsi":        meta.get("MMSI"),
        "ship_name":   (meta.get("ShipName") or "Unknown").strip(),
        "lat":         lat,
        "lon":         lon,
        "waktu":       meta.get("time_utc"),
        "msg_type":    msg_type,
        "speed":       None,
        "course":      None,
        "heading":     None,
        "nav_status":  None,
        "destination": None,
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


async def ais_stream():
    uri = "wss://stream.aisstream.io/v0/stream"
    while True:
        try:
            async with websockets.connect(
                uri,
                ping_interval=30,   # kirim ping tiap 30 detik
                ping_timeout=60,    # tunggu pong max 60 detik
                close_timeout=10,
            ) as ws:
                await ws.send(json.dumps({
                    "APIKey": API_KEY,
                    "BoundingBoxes": REGIONS,
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                }))
                print("✅ Terhubung ke AIS stream")
                async for raw in ws:
                    data = parse(json.loads(raw))
                    if data:
                        await broadcast(data)
            print("⚠️  Koneksi AIS ditutup server — reconnect...")
        except websockets.exceptions.ConnectionClosedError as e:
            print(f"⚠️  Koneksi AIS terputus ({e.code}) — reconnect 5s...")
        except Exception as e:
            print(f"❌ AIS error: {type(e).__name__}: {e} — reconnect 5s...")
        await asyncio.sleep(5)


async def browser_keepalive(websocket: WebSocket):
    """Kirim ping ke browser tiap 20 detik agar koneksi tidak timeout."""
    try:
        while True:
            await asyncio.sleep(20)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(ais_stream())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    ping_task = asyncio.create_task(browser_keepalive(websocket))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        clients.discard(websocket)


@app.get("/")
async def index():
    return HTMLResponse(Path("index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
