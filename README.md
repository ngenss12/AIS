# MAP — Maritime AIS & GFW Viewer

Peta kapal realtime untuk perairan Indonesia menggunakan data AISStream dan Global Fishing Watch (GFW).

## Fitur

- **AIS Live** — posisi kapal realtime via WebSocket langsung ke AISStream
- **GFW Events** — data kejadian kapal (fishing, encounter, loitering) 7–30 hari terakhir
- **Filter rentang waktu** — pilih 1, 3, 7, 14, atau 30 hari untuk data GFW
- Marker warna berdasarkan kecepatan (AIS) atau tipe event (GFW)
- Popup detail kapal: MMSI, kecepatan, tujuan, durasi event

## Struktur

```
local/          → versi untuk development lokal
  server.py     → FastAPI + WebSocket server + background tasks
  index.html    → frontend (connect ke ws://localhost:8000/ws)

vercel/         → versi untuk deployment Vercel
  index.html    → frontend (connect langsung ke AISStream)
  api/
    gfw.py      → Vercel serverless function (proxy GFW API)
  requirements.txt
  vercel.json
```

## Menjalankan Lokal

```bash
pip install fastapi uvicorn websockets httpx
python local/server.py
```

Buka `http://localhost:8000`

## Deploy ke Vercel

1. Push repo ini ke GitHub
2. Import ke [vercel.com](https://vercel.com)
3. Set **Root Directory** → `vercel`
4. Deploy

## Sumber Data

- [AISStream.io](https://aisstream.io) — data AIS realtime
- [Global Fishing Watch](https://globalfishingwatch.org) — data aktivitas penangkapan ikan
