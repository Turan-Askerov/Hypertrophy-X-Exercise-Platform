import os
import shutil

backend_dir = "/home/turan/Desktop/Hypertrophy-X-v4.0/backend"
new_dir = os.path.join(backend_dir, "expert_system")
rules_dir = os.path.join(new_dir, "rules")

os.makedirs(rules_dir, exist_ok=True)

# 1. fuzzy_logic.py
with open(os.path.join(new_dir, "fuzzy_logic.py"), "w") as f:
    f.write("""\
def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))

def rising(value: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0 if value >= end else 0.0
    return _clamp((float(value) - start) / (end - start))

def falling(value: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0 if value <= start else 0.0
    return _clamp((end - float(value)) / (end - start))
""")

# We need to preserve the imports and exactly the logic.
