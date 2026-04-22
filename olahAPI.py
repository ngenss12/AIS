import asyncio
import websockets
import json
import csv
import os
import folium
import pandas as pd

API_KEY = "cadc1da33463ea00ff85c0c1d8506ce3b8a57fcd"  # ganti dengan API key kamu (dari .env)


REGIONS = {
    "Laut Jawa":         [[-8.0, 105.0], [-4.0, 116.0]],
    "Selat Malaka":      [[1.0, 99.0], [6.0, 104.0]],
    "Perairan Surabaya": [[-8.0, 112.0], [-6.5, 113.5]],
}

SELECTED = [v for v in REGIONS.values()]
MAX_DATA = 50

async def stream_ais():
    uri = "wss://stream.aisstream.io/v0/stream"
    records = []

    try:
        async with websockets.connect(uri) as websocket:
            subscribe_msg = {
                "APIKey": API_KEY,
                "BoundingBoxes": SELECTED,
                "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
            }

            await websocket.send(json.dumps(subscribe_msg))
            print(f"✅ Terhubung. Mengambil {MAX_DATA} data...\n")

            async for raw_msg in websocket:
                msg = json.loads(raw_msg)
                parsed = parse(msg)

                if parsed:
                    records.append(parsed)
                    current = len(records)
                    print(f"[{current}/{MAX_DATA}] {parsed['ship_name']} | {parsed['lat']}, {parsed['lon']} | {parsed['speed']} kn")

                    if current >= MAX_DATA:
                        break

    except websockets.exceptions.ConnectionClosedError as e:
        print(f"❌ Koneksi terputus: {e}")
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")

    if records:
        simpan_csv(records)
        plot_peta(records)

    return records


def parse(msg):
    msg_type = msg.get("MessageType")
    meta = msg.get("MetaData", {})

    base = {
        "msg_type":   msg_type,
        "mmsi":       meta.get("MMSI"),
        "ship_name":  meta.get("ShipName", "").strip(),
        "lat":        meta.get("latitude"),
        "lon":        meta.get("longitude"),
        "waktu":      meta.get("time_utc"),
        "speed":      None,
        "course":     None,
        "heading":    None,
        "nav_status": None,
        "ship_type":  None,
        "destination": None,
        "draught":    None,
    }

    if msg_type == "PositionReport":
        pr = msg.get("Message", {}).get("PositionReport", {})
        base["speed"]      = pr.get("Sog")
        base["course"]     = pr.get("Cog")
        base["heading"]    = pr.get("TrueHeading")
        base["nav_status"] = pr.get("NavigationalStatus")

    elif msg_type == "ShipStaticData":
        sd = msg.get("Message", {}).get("ShipStaticData", {})
        base["ship_type"]   = sd.get("Type")
        base["destination"] = sd.get("Destination", "").strip()
        base["draught"]     = sd.get("MaximumStaticDraught")

    return base


def simpan_csv(records, filename="ais_indonesia.csv"):
    fieldnames = records[0].keys()
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"\n💾 CSV disimpan: {filename} — {len(records)} baris")


def plot_peta(records, filename="ais_peta.html"):
    df = pd.DataFrame(records)

    # Filter hanya yang punya koordinat valid
    df = df.dropna(subset=["lat", "lon"])

    if df.empty:
        print("⚠️ Tidak ada data koordinat valid untuk diplot")
        return

    # Warna berdasarkan kecepatan
    def warna(speed):
        if speed is None:  return "gray"
        if speed < 1:      return "red"      # berhenti/jangkar
        if speed < 5:      return "orange"   # lambat
        if speed < 12:     return "blue"     # normal
        return "green"                        # cepat

    # Inisialisasi peta — center di tengah Indonesia
    peta = folium.Map(location=[-2.5, 117.0], zoom_start=5, tiles="CartoDB positron")

    # Tambah marker tiap kapal
    for _, row in df.iterrows():
        speed = row.get("speed")
        name  = row.get("ship_name") or "Unknown"
        mmsi  = row.get("mmsi")
        waktu = row.get("waktu")
        dest  = row.get("destination") or "-"

        popup_html = f"""
        <b>🚢 {name}</b><br>
        MMSI     : {mmsi}<br>
        Speed    : {speed} kn<br>
        Course   : {row.get('course')}°<br>
        Tujuan   : {dest}<br>
        Waktu    : {waktu}
        """

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=6,
            color=warna(speed),
            fill=True,
            fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=name
        ).add_to(peta)

    # Legenda warna
    legenda = """
    <div style="position:fixed; bottom:30px; left:30px; z-index:1000;
                background:white; padding:10px; border-radius:8px;
                border:1px solid #ccc; font-size:13px;">
        <b>Kecepatan Kapal</b><br>
        <span style="color:red">●</span> Berhenti (&lt;1 kn)<br>
        <span style="color:orange">●</span> Lambat (1–5 kn)<br>
        <span style="color:blue">●</span> Normal (5–12 kn)<br>
        <span style="color:green">●</span> Cepat (&gt;12 kn)<br>
        <span style="color:gray">●</span> Tidak diketahui
    </div>
    """
    peta.get_root().html.add_child(folium.Element(legenda))

    peta.save(filename)
    print(f"🗺️  Peta disimpan: {filename} — buka di browser")


asyncio.run(stream_ais())