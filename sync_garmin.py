import os
import json
import datetime
from garminconnect import Garmin

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")

def login_garmin():
    client = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    client.login()
    return client

def sync_activities(client):
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=14)
    print(f"Scaricamento attività dal {start_date} al {today}...")
    
    try:
        activities = client.get_activities_by_date(start_date.isoformat(), today.isoformat(), "running")
    except Exception as e:
        print(f"Nessuna attività scaricata o errore: {e}")
        activities = []

    # Carica il file locale se esiste
    existing_activities = []
    if os.path.exists("activities.json"):
        try:
            with open("activities.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                existing_activities = data if isinstance(data, list) else data.get("activities", [])
        except Exception:
            existing_activities = []

    existing_ids = {str(a.get("id")) for a in existing_activities}
    new_found = 0

    for act in activities:
        act_id = str(act.get("activityId"))
        if act_id not in existing_ids:
            start_time = act.get("startTimeLocal", "")
            try:
                dt = datetime.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1000)
            except Exception:
                ts = int(datetime.datetime.now().timestamp() * 1000)

            dist_km = act.get("distance", 0.0) / 1000.0
            duration_sec = act.get("duration", 0.0)
            elev_gain = act.get("elevationGain", 0.0) or 0.0

            item = {
                "id": "garmin_" + act_id,
                "title": act.get("activityName", "Corsa"),
                "startTime": ts,
                "dateStr": act.get("startTimeLocal", "")[:10],
                "totalDistKm": round(dist_km, 2),
                "totalElevationGain": round(elev_gain),
                "totalElevationLoss": 0,
                "totalTimeSec": round(duration_sec),
                "avgPaceSec": round(duration_sec / dist_km) if dist_km > 0 else 0,
                "globalNgpSec": round(duration_sec / dist_km) if dist_km > 0 else 0,
                "intensityFactor": 0.85,
                "rTSS": round((duration_sec / 3600.0) * 60),
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
        print(f"Salvate {new_found} nuove attività in activities.json.")
    else:
        print("Nessuna nuova attività trovata.")

def push_scheduled_workouts(client):
    if not os.path.exists("scheduled_workouts.json"):
        print("Nessun file scheduled_workouts.json trovato. Salto la pianificazione.")
        return

    try:
        with open("scheduled_workouts.json", "r", encoding="utf-8") as f:
            workouts = json.load(f)
    except Exception as e:
        print(f"Errore lettura scheduled_workouts.json: {e}")
        return

    if not workouts:
        return

    print(f"Trovati {len(workouts)} allenamenti in scheduled_workouts.json. Sincronizzazione con Garmin Connect...")
    today_str = datetime.date.today().isoformat()

    for w in workouts:
        date_str = w.get("date") # Formato YYYY-MM-DD
        if not date_str or date_str < today_str:
            continue # Salta allenamenti passati

        workout_name = w.get("name", "Allenamento Pro")
        duration_mins = w.get("durationMinutes", 45)
        description = w.get("description", "Allenamento pianificato dalla dashboard")

        # Payload strutturato compatibile con Garmin Connect
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
            print(f"Caricamento workout: {workout_name} per il {date_str}...")
            res = client.upload_workout(json.dumps(workout_payload))
            workout_id = res.get("workoutId") or res.get("workout_id")
            if workout_id:
                client.schedule_workout(workout_id, date_str)
                print(f"✅ Workout '{workout_name}' programmato con successo per il {date_str}!")
            else:
                print(f"Workout caricato ma ID non restituito: {res}")
        except Exception as e:
            print(f"Nota/Errore upload workout '{workout_name}': {e}")

if __name__ == "__main__":
    if not GARMIN_EMAIL or not GARMIN_PASSWORD:
        print("Credenziali Garmin non impostate.")
        exit(1)
    
    gc = login_garmin()
    sync_activities(gc)
    push_scheduled_workouts(gc)
