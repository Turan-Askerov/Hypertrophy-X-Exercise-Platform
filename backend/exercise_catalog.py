"""Hypertrophy-X kanonik egzersiz kataloğu.

Bu dosya yalnızca havuz ve analiz meta verisini içerir. API, veritabanı ve
kanonik çözümleme mantığı backend/main.py içinde kalır; böylece katalog
üzerinde düzenleme yapmak güvenli ve kolay olur.
"""

# ═══════════════════════════════════════════════
# EGZERSİZ HAVUZU — KULLANICI DENEYİMİ SABİT, ANALİZ META VERİSİ ZENGİN
# ═══════════════════════════════════════════════
# İlk beş alan (id, name, muscle_group, category, is_bodyweight) mevcut frontend
# ile geriye uyumludur. `analysis` altındaki bilgi kullanıcıya form alanı olarak
# gösterilmez; uzman sistemi ve arka plan raporları tarafından kullanılır.
#
# load_mode değerleri:
# - external_load: yalnızca harici yük (barbell, dumbbell, cable, makine)
# - bodyweight: yalnızca vücut ağırlığıyla kaydedilir
# - bodyweight_plus_external: vücut ağırlığı + plaka/kemer yükü
#
# fatigue_cost; tıbbi risk sınıfı değildir. Programda yorgunluk dağılımı için
# ayarlanabilir bir uzman sistem etiketi olarak tutulur.
EXERCISE_META_VERSION = 3

def _exercise(
    exercise_id, name, muscle_group, category, is_bodyweight,
    *, family, variation, primary_muscles, secondary_muscles,
    movement_pattern, equipment, load_mode, unilateral=False,
    minimum_level="beginner", fatigue_cost="medium",
    contraction_type=None
):
    if contraction_type is None:
        contraction_type = ["concentric", "eccentric"]
        
    return {
        # Mevcut arayüz ve eski kayıtlarla uyumlu alanlar
        "id": exercise_id,
        "name": name,
        "muscle_group": muscle_group,
        "category": category,
        "is_bodyweight": is_bodyweight,

        # Sadece analiz / uzman sistemi için kullanılan görünmez meta veri
        "analysis": {
            "family": family,
            "variation": variation,
            "primary_muscles": primary_muscles,
            "secondary_muscles": secondary_muscles,
            "movement_pattern": movement_pattern,
            "equipment": equipment,
            "load_mode": load_mode,
            "unilateral": unilateral,
            "minimum_level": minimum_level,
            "fatigue_cost": fatigue_cost,
            "contraction_type": contraction_type,
        },
    }


EXERCISE_POOL = [

    # ── GÖĞÜS EGZERSİZLERİ ──────────────────────────────────────────
    # --- Bileşik (Compound) Egzersizler ---
    _exercise("bench-press", "Bench Press", "Chest", "compound", False,
              family="bench_press", variation="barbell_flat", primary_muscles=["chest"],
              secondary_muscles=["triceps", "front_delts"], movement_pattern="horizontal_press",
              equipment=["barbell", "flat_bench"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("dumbbell-bench-press", "Dumbbell Bench Press", "Chest", "compound", False,
              family="bench_press", variation="dumbbell_flat", primary_muscles=["chest"],
              secondary_muscles=["triceps", "front_delts"], movement_pattern="horizontal_press",
              equipment=["dumbbell", "flat_bench"], load_mode="external_load", unilateral=True, fatigue_cost="medium"),

    _exercise("incline-bench-press", "Incline Bench Press", "Chest", "compound", False,
              family="bench_press", variation="barbell_incline", primary_muscles=["upper_chest", "front_delts"],
              secondary_muscles=["triceps"], movement_pattern="incline_press",
              equipment=["barbell", "adjustable_bench"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("incline-dumbbell-press", "Incline Dumbbell Press", "Chest", "compound", False,
              family="bench_press", variation="dumbbell_incline", primary_muscles=["upper_chest", "front_delts"],
              secondary_muscles=["triceps"], movement_pattern="incline_press",
              equipment=["dumbbell", "adjustable_bench"], load_mode="external_load", unilateral=True, fatigue_cost="medium"),

    _exercise("decline-bench-press", "Decline Bench Press", "Chest", "compound", False,
              family="bench_press", variation="barbell_decline", primary_muscles=["chest"],
              secondary_muscles=["triceps", "front_delts"], movement_pattern="decline_press",
              equipment=["barbell", "decline_bench"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("chest-press-machine", "Chest Press Machine", "Chest", "compound", False,
              family="chest_press", variation="selectorized_machine", primary_muscles=["chest"],
              secondary_muscles=["triceps", "front_delts"], movement_pattern="horizontal_press",
              equipment=["chest_press_machine"], load_mode="external_load", fatigue_cost="low"),

    _exercise("push-ups-bw", "Push Ups", "Chest", "compound", True,
              family="push_up", variation="bodyweight", primary_muscles=["chest"],
              secondary_muscles=["triceps", "front_delts"], movement_pattern="horizontal_press",
              equipment=["bodyweight", "floor"], load_mode="bodyweight", fatigue_cost="low"),

    _exercise("push-ups-weighted", "Push Ups", "Chest", "compound", False,
              family="push_up", variation="weighted", primary_muscles=["chest"],
              secondary_muscles=["triceps", "front_delts"], movement_pattern="horizontal_press",
              equipment=["bodyweight", "weight_plate_or_vest", "floor"], load_mode="bodyweight_plus_external", fatigue_cost="medium"),

    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("cable-cross-over", "Cable Cross Over", "Chest", "isolation", False,
              family="chest_fly", variation="cable", primary_muscles=["chest"], secondary_muscles=[],
              movement_pattern="chest_adduction", equipment=["cable_machine"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("dumbbell-flyes", "Dumbbell Flyes", "Chest", "isolation", False,
              family="chest_fly", variation="dumbbell", primary_muscles=["chest"], secondary_muscles=[],
              movement_pattern="chest_adduction", equipment=["dumbbell", "flat_bench"],
              load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("pec-deck-fly", "Pec Deck Fly", "Chest", "isolation", False,
              family="chest_fly", variation="machine", primary_muscles=["chest"], secondary_muscles=["front_delts", "biceps"],
              movement_pattern="chest_adduction", equipment=["pec_deck_machine"],
              load_mode="external_load", unilateral=False, fatigue_cost="low"),

    # ── SIRT EGZERSİZLERİ ──────────────────────────────────────────
    # --- Bileşik (Compound) Egzersizler ---

    _exercise("barbell-row", "Barbell Row", "Back", "compound", False,
              family="row", variation="barbell_bent_over", primary_muscles=["lats"],
              secondary_muscles=["biceps", "rear_delts", "med_trap", "spinal_erectors"], movement_pattern="horizontal_pull",
              equipment=["barbell"], load_mode="external_load", fatigue_cost="high"),

    _exercise("lat-pull-down", "Lat Pull Down", "Back", "compound", False,
              family="lat_pulldown", variation="cable", primary_muscles=["lats"],
              secondary_muscles=["biceps", "upper_back", "rear_delts"], movement_pattern="vertical_pull",
              equipment=["lat_pulldown_machine"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("single-arm-low-row", "Single-Arm Low Row (90-90)", "Back", "compound", False,
              family="row", variation="single_arm_low", primary_muscles=["upper_back", "rear_delts"],
              secondary_muscles=["biceps", "mid_trap"], movement_pattern="horizontal_pull",
              equipment=["cable_machine_or_machine", "single_handle"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("single-arm-pulldown", "Single-Arm Pulldown", "Back", "compound", False,
              family="lat_pulldown", variation="single_arm", primary_muscles=["lats"],
              secondary_muscles=["biceps", "upper_back", "rear_delts"], movement_pattern="vertical_pull",
              equipment=["cable_machine", "single_handle"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("pull-ups-bw", "Pull Ups (Barfiks)", "Back", "compound", True,
              family="pull_up", variation="bodyweight_pronated", primary_muscles=["lats"],
              secondary_muscles=["biceps", "upper_back", "rear_delts"], movement_pattern="vertical_pull",
              equipment=["pull_up_bar", "bodyweight"], load_mode="bodyweight", fatigue_cost="medium"),

    _exercise("weighted-pull-up", "Weighted Pull Up (Barfiks)", "Back", "compound", False,
              family="pull_up", variation="weighted_pronated", primary_muscles=["lats"],
              secondary_muscles=["biceps", "upper_back", "rear_delts"], movement_pattern="vertical_pull",
              equipment=["pull_up_bar", "bodyweight", "dip_belt"], load_mode="bodyweight_plus_external",
              minimum_level="intermediate", fatigue_cost="high"),

    _exercise("chin-ups-bw", "Chin Ups", "Back", "compound", True,
              family="chin_up", variation="bodyweight_supinated", primary_muscles=["lats", "biceps"],
              secondary_muscles=["upper_back", "rear_delts"], movement_pattern="vertical_pull",
              equipment=["pull_up_bar", "bodyweight"], load_mode="bodyweight", fatigue_cost="medium"),

    _exercise("chin-ups-weighted", "Chin Ups", "Back", "compound", False,
              family="chin_up", variation="weighted_supinated", primary_muscles=["lats", "biceps"],
              secondary_muscles=["upper_back", "rear_delts"], movement_pattern="vertical_pull",
              equipment=["pull_up_bar", "bodyweight", "dip_belt"], load_mode="bodyweight_plus_external",
              minimum_level="intermediate", fatigue_cost="high"),

    _exercise("bent-over-row", "Bent-over Row", "Back", "compound", False,
              family="row", variation="free_weight_bent_over", primary_muscles=["lats"],
              secondary_muscles=["biceps", "rear_delts", "med_trap", "spinal_erectors"], movement_pattern="horizontal_pull",
              equipment=["barbell_or_dumbbell"], load_mode="external_load", fatigue_cost="high"),

    _exercise("chest-supported-cable-row", "Chest-Supported Cable Row", "Back", "compound", False,
              family="row", variation="chest_supported_cable", primary_muscles=["mid_traps"],
              secondary_muscles=["rhomboids", "lats", "biceps"], movement_pattern="horizontal_pull",
              equipment=["cable_machine", "bench", "single_handle"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("dumbbell-low-row", "Dumbbell Low Row", "Back", "compound", False,
              family="row", variation="dumbbell_low", primary_muscles=["lats"],
              secondary_muscles=["upper_back", "biceps", "rear_delts"], movement_pattern="horizontal_pull",
              equipment=["dumbbells"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("seated-row", "Seated Row", "Back", "compound", False,
              family="row", variation="seated_cable", primary_muscles=["upper_back", "lats"],
              secondary_muscles=["biceps", "rear_delts"], movement_pattern="horizontal_pull",
              equipment=["cable_row_machine"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("t-bar-row", "T-Bar Row", "Back", "compound", False,
              family="row", variation="t_bar", primary_muscles=["upper_back", "lats"],
              secondary_muscles=["biceps", "rear_delts", "spinal_erectors"], movement_pattern="horizontal_pull",
              equipment=["t_bar_row_machine_or_landmine"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("inverted-row-bw", "Inverted Row", "Back", "compound", True,
              family="inverted_row", variation="bodyweight", primary_muscles=["upper_back", "lats"],
              secondary_muscles=["biceps", "rear_delts"], movement_pattern="horizontal_pull",
              equipment=["bar_or_suspension_trainer", "bodyweight"], load_mode="bodyweight", fatigue_cost="low"),

    _exercise("deadlift", "Deadlift", "Back", "compound", False,
              family="deadlift", variation="barbell_conventional", primary_muscles=["glutes", "hamstrings", "spinal_erectors"],
              secondary_muscles=["upper_back", "traps", "quads"], movement_pattern="hip_hinge",
              equipment=["barbell"], load_mode="external_load", minimum_level="intermediate", fatigue_cost="high"),

    # --- İzolasyon (Isolation) Egzersizleri ---

    _exercise("barbell-shrugs", "Barbell Shrugs", "Back", "isolation", False,
              family="shrug", variation="barbell", primary_muscles=["upper_traps"], secondary_muscles=["levator_scapulae"],
              movement_pattern="scapular_elevation", equipment=["barbell"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("dumbbell-shrugs", "Dumbbell Shrugs", "Back", "isolation", False,
              family="shrug", variation="dumbbell", primary_muscles=["upper_traps"], secondary_muscles=["levator_scapulae"],
              movement_pattern="scapular_elevation", equipment=["dumbbell"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("hyperextension-bw", "Hyperextension", "Back", "isolation", True,
              family="hyperextension", variation="bodyweight", primary_muscles=["spinal_erectors"],
              secondary_muscles=["glutes", "hamstrings"], movement_pattern="spinal_extension",
              equipment=["hyperextension_bench", "bodyweight"], load_mode="bodyweight", fatigue_cost="low"),

    _exercise("hyperextension-weighted", "Hyperextension", "Back", "isolation", False,
              family="hyperextension", variation="weighted", primary_muscles=["spinal_erectors"],
              secondary_muscles=["glutes", "hamstrings"], movement_pattern="spinal_extension",
              equipment=["hyperextension_bench", "dumbbell_or_plate"], load_mode="bodyweight_plus_external",
              fatigue_cost="medium"),

    _exercise("cable-scapular-retraction", "Cable Scapular Retraction", "Back", "isolation", False,
              family="scapular_retraction", variation="cable", primary_muscles=["rhomboids"],
              secondary_muscles=["mid_traps"], movement_pattern="scapular_retraction",
              equipment=["cable_machine", "rope_or_handles"], load_mode="external_load", fatigue_cost="low"),

    _exercise("chest-supported-dumbbell-scapular-retraction", "Chest-Supported Dumbbell Scapular Retraction", "Back", "isolation", False,
              family="scapular_retraction", variation="chest_supported_dumbbell", primary_muscles=["rhomboids"],
              secondary_muscles=["mid_traps"], movement_pattern="scapular_retraction",
              equipment=["dumbbell", "incline_bench"], load_mode="external_load", fatigue_cost="low"),

    _exercise("machine-scapular-retraction", "Machine Scapular Retraction", "Back", "isolation", False,
              family="scapular_retraction", variation="selectorized_machine", primary_muscles=["rhomboids"],
              secondary_muscles=["mid_traps"], movement_pattern="scapular_retraction",
              equipment=["seated_row_machine"], load_mode="external_load", fatigue_cost="low"),

    _exercise("cable-y-raise", "Cable Y Raise", "Back", "isolation", False,
              family="scapular_upward_rotation", variation="cable_y_raise", primary_muscles=["lower_traps"],
              secondary_muscles=["rear_delts"], movement_pattern="scapular_upward_rotation",
              equipment=["cable_machine", "single_handle"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("cable-serratus-punch", "Cable Serratus Punch", "Back", "isolation", False,
              family="serratus_punch", variation="cable", primary_muscles=["serratus_anterior"],
              secondary_muscles=[], movement_pattern="scapular_protraction",
              equipment=["cable_machine", "single_handle"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    # ── OMUZ EGZERSİZLERİ ──────────────────────────────────────────
    # --- Bileşik (Compound) Egzersizler ---
    _exercise("arnold-press", "Arnold Press", "Shoulders", "compound", False,
              family="shoulder_press", variation="arnold_dumbbell", primary_muscles=["front_delts", "side_delts"],
              secondary_muscles=["triceps"], movement_pattern="vertical_press",
              equipment=["dumbbell", "bench_optional"], load_mode="external_load", unilateral=True, fatigue_cost="medium"),

    _exercise("dumbbell-shoulder-press", "Dumbbell Shoulder Press", "Shoulders", "compound", False,
              family="shoulder_press", variation="dumbbell", primary_muscles=["front_delts"],
              secondary_muscles=["triceps", "side_delts"], movement_pattern="vertical_press",
              equipment=["dumbbell", "bench_optional"], load_mode="external_load", unilateral=True, fatigue_cost="medium"),

    _exercise("overhead-press", "Overhead Press", "Shoulders", "compound", False,
              family="shoulder_press", variation="barbell_standing", primary_muscles=["front_delts", "side_delts"],
              secondary_muscles=["triceps"], movement_pattern="vertical_press",
              equipment=["barbell"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("shoulder-press", "Shoulder Press", "Shoulders", "compound", False,
              family="shoulder_press", variation="generic", primary_muscles=["front_delts", "side_delts"],
              secondary_muscles=["triceps"], movement_pattern="vertical_press",
              equipment=["free_weight_or_machine"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("shoulder-press-machine", "Shoulder Press Machine", "Shoulders", "compound", False,
              family="shoulder_press", variation="machine", primary_muscles=["front_delts"],
              secondary_muscles=["triceps", "side_delts"], movement_pattern="vertical_press",
              equipment=["shoulder_press_machine"], load_mode="external_load", fatigue_cost="low"),

    _exercise("upright-row", "Upright Row", "Shoulders", "compound", False,
              family="upright_row", variation="bar", primary_muscles=["side_delts"],
              secondary_muscles=["biceps"], movement_pattern="vertical_pull_upright", equipment=["bar"],
              load_mode="external_load", minimum_level="intermediate", fatigue_cost="medium"),

    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("face-pulls", "Face Pulls", "Shoulders", "isolation", False,
              family="face_pull", variation="cable_rope", primary_muscles=["rear_delts", "upper_back"],
              secondary_muscles=["traps"], movement_pattern="external_rotation_pull", equipment=["cable_machine", "rope"],
              load_mode="external_load", fatigue_cost="low"),

    _exercise("dumbbell-front-raises", "Dumbbell Front Raises", "Shoulders", "isolation", False,
              family="front_raise", variation="dumbbell", primary_muscles=["front_delts"], secondary_muscles=[],
              movement_pattern="shoulder_flexion", equipment=["dumbbell"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("cable-lateral-raises", "Cable Lateral Raises", "Shoulders", "isolation", False,
              family="lateral_raise", variation="cable", primary_muscles=["side_delts"], secondary_muscles=[],
              movement_pattern="shoulder_abduction", equipment=["cable_machine"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("lateral-raises", "Lateral Raises", "Shoulders", "isolation", False,
              family="lateral_raise", variation="dumbbell", primary_muscles=["side_delts"], secondary_muscles=[],
              movement_pattern="shoulder_abduction", equipment=["dumbbell"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("cable-rear-delt-fly", "Cable Rear Delt Fly", "Shoulders", "isolation", False,
              family="rear_delt_fly", variation="cable", primary_muscles=["rear_delts"], secondary_muscles=[],
              movement_pattern="horizontal_abduction", equipment=["cable_machine"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("rear-delt-fly", "Reverse Pec Deck Fly", "Shoulders", "isolation", False,
              family="rear_delt_fly", variation="machine", primary_muscles=["rear_delts"], secondary_muscles=["traps", "upper_back"],
              movement_pattern="horizontal_abduction", equipment=["pec_deck_machine"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("dumbbell-rear-delt-fly", "Dumbbell Reverse Fly", "Shoulders", "isolation", False,
              family="rear_delt_fly", variation="dumbbell", primary_muscles=["rear_delts"], secondary_muscles=[("middle_traps")],
              movement_pattern="horizontal_abduction", equipment=["dumbbell", "bench_optional"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    # ── BACAK EGZERSİZLERİ ──────────────────────────────────────────
    # --- Bileşik (Compound) Egzersizler ---
    _exercise("squat", "Squat", "Legs", "compound", False,
              family="squat", variation="barbell_back", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings", "spinal_erectors"], movement_pattern="squat",
              equipment=["barbell", "squat_rack"], load_mode="external_load", fatigue_cost="high"),

    _exercise("bodyweight-squat", "Dip Squat", "Legs", "compound", True,
              family="squat", variation="bodyweight", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings", "spinal_erectors"], movement_pattern="squat",
              equipment=["bodyweight"], load_mode="bodyweight", fatigue_cost="low"),

    _exercise("front-squat", "Front Squat", "Legs", "compound", False,
              family="squat", variation="barbell_front", primary_muscles=["quads"],
              secondary_muscles=["glutes", "spinal_erectors"], movement_pattern="squat",
              equipment=["barbell", "squat_rack"], load_mode="external_load", minimum_level="intermediate", fatigue_cost="high"),

    _exercise("dip-squat-weighted", "Dip Squat", "Legs", "compound", False,
              family="squat", variation="weighted", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings", "spinal_erectors"], movement_pattern="squat",
              equipment=["dumbbell_or_barbell"], load_mode="external_load", fatigue_cost="high"),

    _exercise("bulgarian-split-squad", "Bulgarian Split Squat", "Legs", "compound", False,
              family="bulgarian_split_squat", variation="weighted", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings", "calves"], movement_pattern="single_leg_squat",
              equipment=["bench", "dumbbell_or_barbell"], load_mode="external_load", unilateral=True, fatigue_cost="high"),

    _exercise("bulgarian-split-squat-bw", "Bulgarian Split Squat", "Legs", "compound", True,
              family="bulgarian_split_squat", variation="bodyweight", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings", "calves"], movement_pattern="single_leg_squat",
              equipment=["bench", "bodyweight"], load_mode="bodyweight", unilateral=True, fatigue_cost="medium"),

    _exercise("glute-bridge-bw", "Glute Bridge", "Legs", "compound", True,
              family="glute_bridge", variation="bodyweight", primary_muscles=["glutes"],
              secondary_muscles=["hamstrings"], movement_pattern="hip_extension", equipment=["bodyweight", "floor"],
              load_mode="bodyweight", fatigue_cost="low"),

    _exercise("glute-bridge", "Glute Bridge", "Legs", "compound", False,
              family="glute_bridge", variation="external_load", primary_muscles=["glutes"],
              secondary_muscles=["hamstrings"], movement_pattern="hip_extension", equipment=["barbell_or_dumbbell", "bench_optional"],
              load_mode="external_load", fatigue_cost="medium"),

    _exercise("hip-thrust", "Hip Thrust", "Legs", "compound", False,
              family="hip_thrust", variation="barbell", primary_muscles=["glutes"],
              secondary_muscles=["hamstrings", "quads"], movement_pattern="hip_extension", equipment=["barbell", "bench"],
              load_mode="external_load", fatigue_cost="medium"),

    _exercise("leg-press", "Leg Press", "Legs", "compound", False,
              family="leg_press", variation="machine", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings"], movement_pattern="leg_press", equipment=["leg_press_machine"],
              load_mode="external_load", fatigue_cost="medium"),

    _exercise("romanian-deadlift", "Romanian Deadlift", "Legs", "compound", False,
              family="romanian_deadlift", variation="free_weight", primary_muscles=["hamstrings", "glutes"],
              secondary_muscles=["spinal_erectors"], movement_pattern="hip_hinge", equipment=["barbell_or_dumbbell"],
              load_mode="external_load", fatigue_cost="high"),

    _exercise("goblet-squat", "Goblet Squat", "Legs", "compound", False,
              family="squat", variation="dumbbell_goblet", primary_muscles=["quads", "glutes"],
              secondary_muscles=["hamstrings"], movement_pattern="squat", equipment=["dumbbell_or_kettlebell"],
              load_mode="external_load", fatigue_cost="medium"),

    _exercise("step-up", "Step-Up", "Legs", "compound", False,
              family="step_up", variation="dumbbell_or_barbell", primary_muscles=["glutes", "quads"],
              secondary_muscles=["hamstrings", "calves"], movement_pattern="single_leg_squat", equipment=["dumbbell_or_barbell", "bench"],
              load_mode="external_load", unilateral=True, fatigue_cost="medium"),

    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("calf-raises-bw", "Calf Raises", "Legs", "isolation", True,
              family="calf_raise", variation="bodyweight", primary_muscles=["calves"], secondary_muscles=[],
              movement_pattern="plantar_flexion", equipment=["bodyweight", "step_optional"], load_mode="bodyweight",
              unilateral=True, fatigue_cost="low"),

    _exercise("seated-calf-raise", "Seated Calf Raise", "Legs", "isolation", False,
              family="calf_raise", variation="seated_machine", primary_muscles=["calves"], secondary_muscles=[],
              movement_pattern="plantar_flexion", equipment=["seated_calf_raise"], load_mode="external_load",
              unilateral=False, fatigue_cost="low"),

    _exercise("smith-machine-calf-raise", "Smith Machine Calf Raise", "Legs", "isolation", False,
              family="calf_raise", variation="standing_smith_machine", primary_muscles=["calves"], secondary_muscles=[],
              movement_pattern="plantar_flexion", equipment=["smith_machine", "step_optional"], load_mode="external_load",
              unilateral=False, fatigue_cost="low"),

    _exercise("standing-calf-raise-barbell", "Standing Calf Raise (Barbell)", "Legs", "isolation", False,
              family="calf_raise", variation="standing_barbell", primary_muscles=["calves"], secondary_muscles=[],
              movement_pattern="plantar_flexion", equipment=["barbell", "step_optional"], load_mode="external_load",
              unilateral=False, fatigue_cost="low"),

    _exercise("calf-raises", "Standing Calf Raise (Dumbbell)", "Legs", "isolation", False,
              family="calf_raise", variation="standing_dumbbell", primary_muscles=["calves"], secondary_muscles=[],
              movement_pattern="plantar_flexion", equipment=["dumbbell", "step_optional"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("cable-hip-abduction", "Cable Hip Abduction", "Legs", "isolation", False,
              family="hip_abduction", variation="standing_cable", primary_muscles=["gluteus_medius"],
              secondary_muscles=[], movement_pattern="hip_abduction",
              equipment=["cable_machine", "ankle_strap"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("cable-hip-adduction", "Cable Hip Adduction", "Legs", "isolation", False,
              family="hip_adduction", variation="standing_cable", primary_muscles=["adductors"],
              secondary_muscles=[], movement_pattern="hip_adduction",
              equipment=["cable_machine", "ankle_strap"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("machine-adductor", "Seated Adductor Machine", "Legs", "isolation", False,
              family="hip_adduction", variation="machine", primary_muscles=["adductors"],
              secondary_muscles=[], movement_pattern="hip_adduction",
              equipment=["adductor_machine"], load_mode="external_load", fatigue_cost="low"),

    _exercise("cable-hip-extension", "Cable Hip Extension", "Legs", "isolation", False,
              family="hip_extension", variation="standing_cable", primary_muscles=["gluteus_maximus"],
              secondary_muscles=["hamstrings"], movement_pattern="hip_extension",
              equipment=["cable_machine", "ankle_strap"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("leg-curl", "Leg Curl", "Legs", "isolation", False,
              family="leg_curl", variation="machine", primary_muscles=["hamstrings"], secondary_muscles=[],
              movement_pattern="knee_flexion", equipment=["leg_curl_machine"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("leg-extension", "Leg Extension", "Legs", "isolation", False,
              family="leg_extension", variation="machine", primary_muscles=["quads"], secondary_muscles=[],
              movement_pattern="knee_extension", equipment=["leg_extension_machine"], load_mode="external_load",
              fatigue_cost="low"),

    # ── CORE EGZERSİZLERİ ──────────────────────────────────────────
    # --- Bileşik (Compound) Egzersizler ---
    _exercise("kettlebell-swings", "Kettlebell Swings", "Core", "compound", False,
              family="kettlebell_swing", variation="kettlebell", primary_muscles=["glutes", "hamstrings"],
              secondary_muscles=["spinal_erectors", "abs"], movement_pattern="hip_hinge_power",
              equipment=["kettlebell"], load_mode="external_load", minimum_level="intermediate", fatigue_cost="high"),

    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("cable-crunches", "Cable Crunches", "Core", "isolation", False,
              family="cable_crunch", variation="cable", primary_muscles=["abs"], secondary_muscles=[],
              movement_pattern="trunk_flexion", equipment=["cable_machine", "rope"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("seated-crunch", "Seated Crunch", "Core", "isolation", False,
              family="crunch", variation="machine", primary_muscles=["abs"], secondary_muscles=[],
              movement_pattern="trunk_flexion", equipment=["ab_crunch_machine"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("russian-twist", "Russian Twist", "Core", "isolation", True,
              family="russian_twist", variation="bodyweight", primary_muscles=["obliques", "abs"], secondary_muscles=[],
              movement_pattern="trunk_rotation", equipment=["bodyweight", "floor"], load_mode="bodyweight",
              fatigue_cost="low"),

    _exercise("weighted-russian-twist", "Russian Twist", "Core", "isolation", False,
              family="russian_twist", variation="weighted", primary_muscles=["obliques", "abs"], secondary_muscles=[],
              movement_pattern="trunk_rotation", equipment=["dumbbell_or_plate", "floor"],
              load_mode="bodyweight_plus_external", fatigue_cost="low"),

    # ── ROTATOR / SKAPULA / KALÇA EGZERSİZLERİ ──────────────────────────────────────────
    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("cable-90-90-external-rotation", "Cable 90/90 External Rotation", "Rotator Cuff", "isolation", False,
              family="shoulder_rotation", variation="cable_90_90_external", primary_muscles=["teres_minor"],
              secondary_muscles=["infraspinatus"], movement_pattern="shoulder_external_rotation",
              equipment=["cable_machine", "single_handle"], load_mode="external_load", unilateral=True, minimum_level="intermediate", fatigue_cost="low"),

    _exercise("cable-shoulder-external-rotation", "Cable Shoulder External Rotation", "Rotator Cuff", "isolation", False,
              family="shoulder_rotation", variation="cable_external_rotation", primary_muscles=["infraspinatus"],
              secondary_muscles=["teres_minor"], movement_pattern="shoulder_external_rotation",
              equipment=["cable_machine", "single_handle"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("cable-shoulder-internal-rotation", "Cable Shoulder Internal Rotation", "Rotator Cuff", "isolation", False,
              family="shoulder_rotation", variation="cable_internal_rotation", primary_muscles=["subscapularis"],
              secondary_muscles=[], movement_pattern="shoulder_internal_rotation",
              equipment=["cable_machine", "single_handle"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    # ── TRICEPS EGZERSİZLERİ ──────────────────────────────────────────
    # --- Bileşik (Compound) Egzersizler ---
    _exercise("close-grip-bench-press", "Close-grip Bench Press", "Triceps", "compound", False,
              family="bench_press", variation="barbell_close_grip", primary_muscles=["triceps"],
              secondary_muscles=["chest", "front_delts"], movement_pattern="horizontal_press",
              equipment=["barbell", "flat_bench"], load_mode="external_load", fatigue_cost="medium"),

    _exercise("dips-bw", "Dips", "Triceps", "compound", True,
              family="dip", variation="bodyweight", primary_muscles=["triceps", "chest"],
              secondary_muscles=["front_delts"], movement_pattern="vertical_press", equipment=["dip_bars", "bodyweight"],
              load_mode="bodyweight", fatigue_cost="medium"),

    _exercise("dips-weighted", "Dips", "Triceps", "compound", False,
              family="dip", variation="weighted", primary_muscles=["triceps", "chest"],
              secondary_muscles=["front_delts"], movement_pattern="vertical_press",
              equipment=["dip_bars", "bodyweight", "dip_belt"], load_mode="bodyweight_plus_external",
              minimum_level="intermediate", fatigue_cost="high"),

    # ── BICEPS EGZERSİZLERİ ──────────────────────────────────────────
    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("bicep-curl", "Barbell Biceps Curl", "Biceps", "isolation", False,
              family="bicep_curl", variation="barbell", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["barbell"], load_mode="external_load",
              unilateral=False, fatigue_cost="low"),

    _exercise("cable-bicep-curl", "Cable Bicep Curl", "Biceps", "isolation", False,
              family="bicep_curl", variation="cable", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["cable_machine"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("concentration-curl", "Concentration Curl", "Biceps", "isolation", False,
              family="bicep_curl", variation="concentration_dumbbell", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["dumbbell", "bench"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("incline-dumbbell-curl", "Incline Dumbbell Curl", "Biceps", "isolation", False,
              family="bicep_curl", variation="incline_dumbbell", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["dumbbell", "adjustable_bench"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("seated-dumbbell-biceps-curl", "Seated Dumbbell Biceps Curl", "Biceps", "isolation", False,
              family="bicep_curl", variation="seated_dumbbell", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["dumbbell", "bench"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("wide-grip-barbell-biceps-curl", "Wide Biceps Curl (Barbell)", "Biceps", "isolation", False,
              family="bicep_curl", variation="wide_grip_barbell", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["barbell"], load_mode="external_load",
              unilateral=False, fatigue_cost="low"),

    _exercise("hammer-curl", "Hammer Curl", "Biceps", "isolation", False,
              family="hammer_curl", variation="dumbbell", primary_muscles=["biceps", "forearms"], secondary_muscles=[],
              movement_pattern="elbow_flexion_neutral", equipment=["dumbbell"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    # ── HIP ROTATORS EGZERSİZLERİ ──────────────────────────────────────────
    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("cable-hip-external-rotation", "Cable Hip External Rotation", "Hip Rotators", "isolation", False,
              family="hip_rotation", variation="standing_cable_external", primary_muscles=["hip_external_rotators"],
              secondary_muscles=["gluteus_medius"], movement_pattern="hip_external_rotation",
              equipment=["cable_machine", "ankle_strap"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    _exercise("cable-hip-internal-rotation", "Cable Hip Internal Rotation", "Hip Rotators", "isolation", False,
              family="hip_rotation", variation="standing_cable_internal", primary_muscles=["hip_internal_rotators"],
              secondary_muscles=[], movement_pattern="hip_internal_rotation",
              equipment=["cable_machine", "ankle_strap"], load_mode="external_load", unilateral=True, fatigue_cost="low"),

    # ── BICEPS EGZERSİZLERİ ──────────────────────────────────────────
    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("preacher-curl", "Preacher Curl", "Biceps", "isolation", False,
              family="preacher_curl", variation="generic", primary_muscles=["biceps"],
              secondary_muscles=["forearms"], movement_pattern="elbow_flexion",
              equipment=["free_weight_or_machine"], load_mode="external_load", fatigue_cost="low"),

    _exercise("preacher-curl-dumbbell", "Preacher Curl (Dumbbell)", "Biceps", "isolation", False,
              family="preacher_curl", variation="dumbbell", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["dumbbell", "preacher_bench"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("preacher-curl-z-bar", "Preacher Curl (Z Bar)", "Biceps", "isolation", False,
              family="preacher_curl", variation="ez_bar", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["ez_bar", "preacher_bench"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("preacher-curl-machine", "Preacher Curl Machine", "Biceps", "isolation", False,
              family="preacher_curl", variation="machine", primary_muscles=["biceps"], secondary_muscles=["forearms"],
              movement_pattern="elbow_flexion", equipment=["preacher_curl_machine"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("reverse-curl", "Reverse Curl (Barbell / EZ Bar)", "Biceps", "isolation", False,
              family="reverse_curl", variation="barbell_or_ez", primary_muscles=["biceps", "forearms"], secondary_muscles=[],
              movement_pattern="elbow_flexion_pronated", equipment=["barbell_or_ez_bar"], load_mode="external_load",
              unilateral=False, fatigue_cost="low"),

    # ── TRICEPS EGZERSİZLERİ ──────────────────────────────────────────
    # --- İzolasyon (Isolation) Egzersizleri ---
    _exercise("cable-rope-overhead-tricep-extension", "Cable Rope Overhead Tricep Extension", "Triceps", "isolation", False,
              family="tricep_extension", variation="overhead_cable", primary_muscles=["triceps"], secondary_muscles=[],
              movement_pattern="overhead_elbow_extension", equipment=["cable_machine", "rope"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("dumbbell-kickbacks", "Dumbbell Kickbacks", "Triceps", "isolation", False,
              family="tricep_extension", variation="kickback_dumbbell", primary_muscles=["triceps"], secondary_muscles=[],
              movement_pattern="elbow_extension", equipment=["dumbbell"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("triceps-extension", "Dumbbell Triceps Extension", "Triceps", "isolation", False,
              family="tricep_extension", variation="dumbbell", primary_muscles=["triceps"],
              secondary_muscles=[], movement_pattern="elbow_extension",
              equipment=["dumbbell"], load_mode="external_load", fatigue_cost="low"),

    _exercise("overhead-tricep-extension", "Overhead Tricep Extension", "Triceps", "isolation", False,
              family="tricep_extension", variation="overhead_free_weight", primary_muscles=["triceps"], secondary_muscles=[],
              movement_pattern="overhead_elbow_extension", equipment=["dumbbell_or_ez_bar"], load_mode="external_load",
              unilateral=True, fatigue_cost="low"),

    _exercise("skull-crushers", "Skull Crushers", "Triceps", "isolation", False,
              family="tricep_extension", variation="lying_free_weight", primary_muscles=["triceps"], secondary_muscles=[],
              movement_pattern="elbow_extension", equipment=["ez_bar_or_dumbbell", "bench"], load_mode="external_load",
              fatigue_cost="low"),

    _exercise("tricep-push-down", "Tricep Push Down", "Triceps", "isolation", False,
              family="tricep_extension", variation="cable_pushdown", primary_muscles=["triceps"], secondary_muscles=[],
              movement_pattern="elbow_extension", equipment=["cable_machine"], load_mode="external_load",
              fatigue_cost="low"),

]