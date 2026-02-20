import json

data = json.load(open("data/signals_history.json"))
print(f"Total signals: {len(data)}")
for s in data[-10:]:
    print(f"  {s['signal_id']} | {s['signal_time_readable']} | {s['status']} | {s['direction']}")
