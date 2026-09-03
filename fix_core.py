import os

core_file = "/home/turan/Desktop/Hypertrophy-X-v4.0/backend/expert_system/core.py"
with open(core_file, "r") as f:
    lines = f.readlines()

constants = """\
UI_MUSCLE_GROUPS = (
    "Göğüs", "Sırt", "Omuz", "Biceps", "Triceps", "Bacak", "Core",
)

PRIMARY_GOALS = {
    "hypertrophy": "Kas kazanımı",
    "strength": "Güç kazanımı",
    "fat_loss": "Yağ kaybı ve kas korunumu",
}

ENGLISH_TO_UI_MUSCLE = {
    "Chest": "Göğüs",
    "Back": "Sırt",
    "Shoulders": "Omuz",
    "Biceps": "Biceps",
    "Triceps": "Triceps",
    "Legs": "Bacak",
    "Core": "Core",
    "Traps": "Sırt",
}

"""

# Find where to insert it. After imports.
# imports end around line 12-13.
# Let's just put it after 'falling\n' which we added.

insert_idx = 0
for i, line in enumerate(lines):
    if "from expert_system.fuzzy_logic" in line:
        insert_idx = i + 1
        break

lines.insert(insert_idx, constants)

with open(core_file, "w") as f:
    f.writelines(lines)

print("Constants added.")
