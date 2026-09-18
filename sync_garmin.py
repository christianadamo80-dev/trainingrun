import os
import json
import datetime
import time
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError
)

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")

def login_garmin():
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        raise ValueError("GARMIN_EMAIL e GARMIN_PASSWORD non sono impostati nei Secrets di GitHub.")
    
    print(f"Tentativo di autenticazione per {GARMIN_EMAIL[:3]}***...")
    try:
        client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
        client.login()
        print("✅ Login Garmin Connect completato con successo!")
        return client
    except GarminConnectAuthenticationError as e:
        print(f"ERRORE AUTENTICAZIONE GARMIN: {e}")
        raise
    except GarminConnectTooManyRequestsError as e:
        print(f"ERRORE RATE LIMIT GARMIN: {e}")
        raise
    except Exception as e:
        print(f"ERRORE CONNESSIONE: {e}")
        raise

def sync_all_activities(client, max_activities=1000):
    """
    Scarica l'intero storico delle attività a blocchi (paginazione).
    """
    print("--- FASE 1: Download storico completo corse da Garmin Connect ---")
    
    # Carica le attività già archiviate localmente per evitare duplicati
    existing_activities = []
    if os.path.exists("activities.json"):
        try:
            with open("activities.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_activities = data if isinstance(data, list) else data.get("activities", [])
        except Exception as e:
            print(f"File activities.json non valido o vuoto: {e}")
            existing_activities = []

    existing_ids = {str(a.get("id")) for a in existing_activities}
    all_downloaded = []
    start = 0
    limit = 100
    new_found = 0

    while start < max_activities:
        print(f"Recupero blocco attività da {start} a {start + limit}...")
        try:
            batch = client.get_activities(start, limit)
        except Exception as e:
            print(f"Interruzione recupero batch: {e}")
            break

        if not batch:
            print("Nessun'altra attività trovata sul server Garmin.")
            break

        for act in batch:
            # Filtra per includere solo attività di corsa e trail running
            sport_type = (act.get("activityType") or {}).get("typeKey", "").lower()
            if "running" not in sport_type and "trail" not in sport_type and "treadmill" not in sport_type:
                continue

            act_id = str(act.get("activityId"))
            formatted_id = "garmin_" + act_id

            if formatted_id in existing_ids or act_id in existing_ids:
                continue

            start_time = act.get("startTimeLocal", "")
            try:
                dt = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1000)
            except Exception:
                ts = int(datetime.datetime.now().timestamp() * 1000)

            dist_km = (act.get("distance", 0.0) or 0.0) / 1000.0
            duration_sec = act.get("duration", 0.0) or 0.0
            elev_gain = act.get("elevationGain", 0.0) or 0.0

            # Calcolo metriche di base per TrainingPeaks
            avg_pace = round(duration_sec / dist_km) if dist_km > 0.05 else 0
            
            # Stima rTSS: se non c'è NGP puntuale usiamo stima intensità/durata
            est_tss = round((duration_sec / 3600.0) * 60) if duration_sec > 0 else 0

            item = {
                "id": formatted_id,
                "athleteId": "ath_default",
                "title": act.get("activityName", "Corsa"),
                "startTime": ts,
                "dateStr": start_time[:10] if start_time else datetime.date.today().isoformat(),
                "totalDistKm": round(dist_km, 2),
                "totalElevationGain": round(elev_gain),
                "totalElevationLoss": 0,
                "totalTimeSec": round(duration_sec),
                "avgPaceSec": avg_pace,
                "globalNgpSec": avg_pace,
                "intensityFactor": 0.85,
                "rTSS": est_tss,
                "kmEffort": round(dist_km + (elev_gain / 100.0), 1),
                "vam": 0,
                "avgHR": round(act.get("averageHR")) if act.get("averageHR") else None,
                "maxHR": round(act.get("maxHR")) if act.get("maxHR") else None,
                "points": []
            }
            all_downloaded.append(item)
            existing_ids.add(formatted_id)
            new_found += 1

        start += limit
        time.sleep(1) # Rispetto delle quote di richiesta (anti rate-limit)

    if new_found > 0:
        # Unisci nuove attività con quelle esistenti e ordina cronologicamente
        combined = existing_activities + all_downloaded
        combined.sort(key=lambda x: x.get("startTime", 0), reverse=True)

        with open("activities.json", "w", encoding="utf-8") as f:
            json.dump(combined, f, indent=2)
        print(f"🎉 Sincronizzazione completata! Aggiunte {new_found} sessioni a activities.json (Totale: {len(combined)}).")
    else:
        print("Tutte le attività risultano già presenti in activities.json.")

def push_scheduled_workouts(client):
    print("--- FASE 2: Invio allenamenti pianificati a Garmin ---")
    if not os.path.exists("scheduled_workouts.json"):
        print("Nessun file scheduled_workouts.json presente.")
        return

    try:
        with open("scheduled_workouts.json", "r", encoding="utf-8") as f:
            workouts = json.load(f)
    except Exception as e:
        print(f"Errore lettura scheduled_workouts.json: {e}")
        return

    if not workouts:
        return

    today_str = datetime.date.today().isoformat()

    for w in workouts:
        date_str = w.get("date")
        if not date_str or date_str < today_str:
            continue

        workout_name = w.get("name", "Workout Pro")
        duration_mins = int(w.get("durationMinutes", 45) or 45)
        description = w.get("description", "Pianificato da Dashboard")

        workout_payload = {
            "workoutName": workout_name,
            "description": description,
            "sportType": {
                "sportTypeId": 1,
                "sportTypeKey": "running"
            },
            "workoutSegments": [
                {
                    "segmentOrder": 1,
                    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
                    "workoutSteps": [
                        {
                            "type": "ExecutableStepDTO",
                            "stepOrder": 1,
                            "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
                            "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
                            "endConditionValue": duration_mins * 60,
                            "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
                        }
                    ]
                }
            ]
        }

        try:
            print(f"Invio workout '{workout_name}' per il {date_str}...")
            try:
                res = client.upload_workout(json.dumps(workout_payload))
            except TypeError:
                res = client.upload_workout(workout_payload)

            w_id = res.get("workoutId") or res.get("workout_id") if isinstance(res, dict) else res
            if w_id:
                client.schedule_workout(str(w_id), date_str)
                print(f"✅ Workout '{workout_name}' schedulato per il {date_str}!")
        except Exception as err:
            print(f"⚠️ Avviso upload workout '{workout_name}': {err}")

if __name__ == "__main__":
    try:
        gc = login_garmin()
    except Exception as e:
        print(f"Login fallito: {e}")
        exit(1)

    try:
        sync_all_activities(gc, max_activities=1500) # Scarica fino a 1500 attività storiche
    except Exception as e:
        print(f"Errore download attività: {e}")

    try:
        push_scheduled_workouts(gc)
    except Exception as e:
        print(f"Errore upload workout: {e}")
