import os
import json
import datetime
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
        print("Login Garmin Connect completato con successo!")
        return client
    except GarminConnectAuthenticationError as e:
        print(f"ERRORE AUTENTICAZIONE GARMIN: Credenziali errate o blocco bot/MFA attivo: {e}")
        raise
    except GarminConnectTooManyRequestsError as e:
        print(f"ERRORE RATE LIMIT GARMIN: Troppe richieste recenti dai server GitHub: {e}")
        raise
    except Exception as e:
        print(f"ERRORE CONNESSIONE: {e}")
        raise

def sync_activities(client):
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=28)
    print(f"--- FASE 1: Download corse dal {start_date} al {today} ---")
    
    try:
        activities = client.get_activities_by_date(start_date.isoformat(), today.isoformat(), "running")
    except Exception as e:
        print(f"Impossibile scaricare le attività da Garmin: {e}")
        return

    # Carica le attività già presenti
    existing_activities = []
    if os.path.exists("activities.json"):
        try:
            with open("activities.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_activities = data if isinstance(data, list) else data.get("activities", [])
        except Exception as e:
            print(f"File activities.json non valido, ne creo uno nuovo: {e}")
            existing_activities = []

    existing_ids = {str(a.get("id")) for a in existing_activities}
    new_found = 0

    for act in activities:
        act_id = str(act.get("activityId"))
        formatted_id = "garmin_" + act_id
        if formatted_id not in existing_ids and act_id not in existing_ids:
            start_time = act.get("startTimeLocal", "")
            try:
                dt = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1000)
            except Exception:
                ts = int(datetime.datetime.now().timestamp() * 1000)

            dist_km = (act.get("distance", 0.0) or 0.0) / 1000.0
            duration_sec = act.get("duration", 0.0) or 0.0
            elev_gain = act.get("elevationGain", 0.0) or 0.0

            item = {
                "id": formatted_id,
                "athleteId": "ath_default",
                "title": act.get("activityName", "Corsa"),
                "startTime": ts,
                "dateStr": act.get("startTimeLocal", "")[:10] if act.get("startTimeLocal") else today.isoformat(),
                "totalDistKm": round(dist_km, 2),
                "totalElevationGain": round(elev_gain),
                "totalElevationLoss": 0,
                "totalTimeSec": round(duration_sec),
                "avgPaceSec": round(duration_sec / dist_km) if dist_km > 0.05 else 0,
                "globalNgpSec": round(duration_sec / dist_km) if dist_km > 0.05 else 0,
                "intensityFactor": 0.85,
                "rTSS": round((duration_sec / 3600.0) * 60) if duration_sec > 0 else 0,
                "kmEffort": round(dist_km + (elev_gain / 100.0), 1),
                "vam": 0,
                "avgHR": round(act.get("averageHR")) if act.get("averageHR") else None,
                "maxHR": round(act.get("maxHR")) if act.get("maxHR") else None,
                "points": []
            }
            existing_activities.append(item)
            new_found += 1

    if new_found > 0 or not os.path.exists("activities.json"):
        with open("activities.json", "w", encoding="utf-8") as f:
            json.dump(existing_activities, f, indent=2)
        print(f"Salvate {new_found} nuove sessioni in activities.json.")
    else:
        print("Nessuna nuova attività trovata.")

def push_scheduled_workouts(client):
    print("--- FASE 2: Invio allenamenti pianificati a Garmin ---")
    if not os.path.exists("scheduled_workouts.json"):
        print("Nessun file scheduled_workouts.json presente. Nessun allenamento da caricare.")
        return

    try:
        with open("scheduled_workouts.json", "r", encoding="utf-8") as f:
            workouts = json.load(f)
    except Exception as e:
        print(f"Errore lettura scheduled_workouts.json: {e}")
        return

    if not workouts:
        print("Lista scheduled_workouts vuota.")
        return

    today_str = datetime.date.today().isoformat()

    for w in workouts:
        date_str = w.get("date")
        if not date_str or date_str < today_str:
            continue

        workout_name = w.get("name", "Workout Pro")
        duration_mins = int(w.get("durationMinutes", 45) or 45)
        description = w.get("description", "Pianificato da Dashboard")

        # Payload strutturato conforme a Garmin Connect
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
                    "sportType": {
                        "sportTypeId": 1,
                        "sportTypeKey": "running"
                    },
                    "workoutSteps": [
                        {
                            "type": "ExecutableStepDTO",
                            "stepOrder": 1,
                            "stepType": {
                                "stepTypeId": 3,
                                "stepTypeKey": "interval"
                            },
                            "endCondition": {
                                "conditionTypeId": 2,
                                "conditionTypeKey": "time"
                            },
                            "endConditionValue": duration_mins * 60,
                            "targetType": {
                                "workoutTargetTypeId": 1,
                                "workoutTargetTypeKey": "no.target"
                            }
                        }
                    ]
                }
            ]
        }

        try:
            print(f"Invio workout '{workout_name}' per data {date_str}...")
            # Tentativo sia con stringa json che dizionario a seconda della versione del client
            try:
                res = client.upload_workout(json.dumps(workout_payload))
            except TypeError:
                res = client.upload_workout(workout_payload)

            w_id = None
            if isinstance(res, dict):
                w_id = res.get("workoutId") or res.get("workout_id")
            elif isinstance(res, (str, int)):
                w_id = res

            if w_id:
                client.schedule_workout(str(w_id), date_str)
                print(f"✅ Workout '{workout_name}' (ID: {w_id}) schedulato per il {date_str}!")
            else:
                print(f"Workout caricato, risposta server: {res}")
        except Exception as err:
            print(f"⚠️ Avviso: Invio workout '{workout_name}' non riuscito: {err}")

if __name__ == "__main__":
    try:
        gc = login_garmin()
    except Exception as e:
        print(f"Interruzione script: login fallito ({e}).")
        exit(1)

    # Esegui le due fasi in modo indipendente
    try:
        sync_activities(gc)
    except Exception as e:
        print(f"Errore durante sync_activities: {e}")

    try:
        push_scheduled_workouts(gc)
    except Exception as e:
        print(f"Errore durante push_scheduled_workouts: {e}")
