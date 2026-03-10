import requests
from datetime import datetime, timezone, timedelta
from data_platform.config import DataPlatformConfig
from data_platform.storage.lake_writer import LakeWriter

def backfill_fear_greed(days=1000):
    print(f"Backfilling Fear & Greed for {days} days...")
    resp = requests.get(
        "https://api.alternative.me/fng/",
        params={"limit": days, "format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    events = []
    for item in data:
        ts = int(item.get("timestamp", 0))
        if ts <= 0: continue
        value = float(item.get("value", 0) or 0)
        classification = str(item.get("value_classification", ""))
        base_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # One row per hour to match market data
        for hour in range(24):
            dt = base_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
            events.append({
                "event_time": dt.isoformat(),
                "value": value,
                "classification": classification,
            })
    
    cfg = DataPlatformConfig()
    writer = LakeWriter(cfg.lake_root)
    writer.write_events_by_event_time(
        "bronze", "alternative_me", "fear_greed_index", events
    )
    print(f"Done: {len(events)} rows written to data_lake.")

if __name__ == "__main__":
    backfill_fear_greed()
