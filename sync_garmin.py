import os
import json
import io
import zipfile
from datetime import datetime
from garminconnect import Garmin
from fitparse import FitFile

GARMIN_EMAIL = os.environ.get("GARMIN_EMAIL")
GARMIN_PASSWORD = os.environ.get("GARMIN_PASSWORD")
OUTPUT_FILE = "activities.json"

def get_garmin_client():
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    # Imposta un User-Agent moderno per evitare blocchi Cloudflare
    client.garth.sess.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    })
    client.login()
    return client

def parse_fit_bytes(fit_bytes, title, start_time_ms):
    fitfile = FitFile(io.BytesIO(fit_bytes))
    points = []
    total_dist = 0
    total_ele_gain = 0
    total_ele_loss = 0
    last_ele = None

    for record in fitfile.get_messages("record"):
        data = {d.name: d.value for d in record}
        lat = data.get("position_lat")
        lon = data.get("position_long")
        if lat is None or lon is None:
            continue

        # Garmin salva in semicircles, convertiamo in gradi
        lat_deg = lat * (180 / 2**31)
        lon_deg = lon * (180 / 2**31)
        alt = data.get("enhanced_altitude") or data.get("altitude") or 0
        dist = data.get("enhanced_distance") or data.get("distance") or 0
        hr = data.get("heart_rate")
        cad = data.get("cadence")
        pwr = data.get("power")
        timestamp = data.get("timestamp")
        time_ms = int(timestamp.timestamp() * 1000) if timestamp else 0

        if last_ele is not None:
            diff = alt - last_ele
            if diff > 0.5:
                total_ele_gain += diff
            elif diff < -0.5:
                total_ele_loss += abs(diff)
        last_ele = alt
        total_dist = max(total_dist, dist)

        points.append({
            "lat": round(lat_deg, 6),
            "lon": round(lon_deg, 6),
            "ele": round(alt, 1),
            "time": time_ms,
            "dist": round(dist, 1),
            "hr": hr,
            "cadence": cad,
            "power": pwr
        })

    if not points:
        return None

    duration_sec = max(1, (points[-1]["time"] - points[0]["time"]) // 1000)
    avg_speed = total_dist / duration_sec if duration_sec > 0 else 0
    avg_pace_sec = round(1000 / avg_speed) if avg_speed > 0.5 else 0

    return {
        "id": f"act_garmin_{start_time_ms}",
        "title": title or "Corsa Garmin",
        "startTime": start_time_ms,
        "dateStr": datetime.fromtimestamp(start_time_ms / 1000).strftime("%Y-%m-%d"),
        "totalDistKm": round(total_dist / 1000, 2),
        "totalElevationGain": round(total_ele_gain),
        "totalElevationLoss": round(total_ele_loss),
        "totalTimeSec": duration_sec,
        "avgPaceSec": avg_pace_sec,
        "globalNgpSec": avg_pace_sec, # Normalizzato dal client all'apertura
        "intensityFactor": 1.0,
        "rTSS": round((duration_sec / 3600) * 60, 1),
        "kmEffort": round((total_dist / 1000) + (total_ele_gain / 100), 1),
        "points": points
    }

def main():
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        print("Credenziali Garmin mancanti nei Secrets.")
        return

    # Carica storico esistente se presente
    existing_activities = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_activities = data if isinstance(data, list) else data.get("activities", [])
        except Exception as e:
            print(f"Errore lettura file esistente: {e}")

    existing_ids = {a["id"] for a in existing_activities}

    print("Connessione a Garmin Connect...")
    client = get_garmin_client()
    print("Login effettuato. Recupero ultime sessioni...")

    # Recupera le ultime 10 corse
    activities = client.get_activities(0, 10)
    new_found = 0

    for act in reversed(activities):
        # Filtra solo le attività di corsa/trail running
        activity_type = act.get("activityType", {}).get("typeKey", "")
        if "running" not in activity_type:
            continue

        act_id = act.get("activityId")
        start_time_str = act.get("startTimeLocal")
        try:
            dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            start_ms = int(dt.timestamp() * 1000)
        except:
            start_ms = int(datetime.now().timestamp() * 1000)

        custom_id = f"act_garmin_{start_ms}"
        if custom_id in existing_ids:
            continue

        title = act.get("activityName", "Corsa")
        print(f"Download nuova corsa: {title} ({act_id})...")

        try:
            # Scarica il file FIT compresso in zip da Garmin
            fit_zip = client.download_activity(act_id, dl_fmt=client.ActivityDownloadFormat.ORIGINAL)
            with zipfile.ZipFile(io.BytesIO(fit_zip)) as z:
                for filename in z.namelist():
                    if filename.endswith(".fit"):
                        with z.open(filename) as fit_file:
                            parsed = parse_fit_bytes(fit_file.read(), title, start_ms)
                            if parsed:
                                existing_activities.append(parsed)
                                existing_ids.add(custom_id)
                                new_found += 1
        except Exception as e:
            print(f"Errore parsing attività {act_id}: {e}")

    if new_found > 0:
        print(f"Salvataggio di {new_found} nuove corse in {OUTPUT_FILE}...")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_activities, f, ensure_ascii=False)
    else:
        print("Nessuna nuova corsa trovata.")

if __name__ == "__main__":
    main()
