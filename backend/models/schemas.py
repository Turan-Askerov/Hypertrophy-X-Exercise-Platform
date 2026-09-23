"""Hypertrophy-X merkezi Pydantic istek ve veri modelleri."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ── Auth Modelleri ──
class AuthRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = ""


class ForgotPasswordRequest(BaseModel):
    email_or_username: str


class VerifyResetCodeRequest(BaseModel):
    reset_token: str
    code: str


class ResetPasswordRequest(BaseModel):
    verified_token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ── Kullanıcı & Profil Modelleri ──
class UserProfile(BaseModel):
    username: str
    email: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    fitness_level: Optional[str] = None
    goal: Optional[str] = None
    days_per_week: Optional[int] = None
    session_time_mins: Optional[int] = None
    new_password: Optional[str] = None


class AdminEditUser(BaseModel):
    user_id: int
    age: Optional[int] = None
    gender: Optional[str] = None
    height: Optional[float] = None
    weight: Optional[float] = None
    fitness_level: Optional[str] = None
    goal: Optional[str] = None
    days_per_week: Optional[int] = None
    session_time_mins: Optional[int] = None
    new_password: Optional[str] = None


# ── Antrenman Modelleri ──
class SetData(BaseModel):
    reps: int
    weight_kg: float = 0
    rir: Optional[int] = None


class ExerciseEntry(BaseModel):
    exercise_id: str
    exercise_name: str
    muscle_group: str
    sets_data: List[SetData]
    is_bodyweight: bool = False
    canonical_exercise_id: Optional[str] = None
    exercise_meta_version: int = 1


class WorkoutCreate(BaseModel):
    date: str
    session_type: str
    notes: Optional[str] = ""
    exercises: List[ExerciseEntry]
    gym_id: Optional[str] = None
    gym_name: Optional[str] = None


class WorkoutUpdate(BaseModel):
    date: Optional[str] = None
    session_type: Optional[str] = None
    notes: Optional[str] = None
    exercises: Optional[List[ExerciseEntry]] = None
    gym_id: Optional[str] = None
    gym_name: Optional[str] = None


# ── Admin & Veritabanı Modelleri ──
class AdminSqlQuery(BaseModel):
    query: str


class AdminMigrateRequest(BaseModel):
    database_url: Optional[str] = None
    dry_run: Optional[bool] = False


class AnalyzeRequest(BaseModel):
    stagnation_detected: Optional[bool] = False


# ── Özel Program & Dashboard Tercihleri ──
class CustomDay(BaseModel):
    day: str
    type: str
    focus: str
    isRest: bool


class CustomProgramRequest(BaseModel):
    username: str
    program: List[List[CustomDay]]


class DashboardPreferencesRequest(BaseModel):
    pr_targets: dict[str, float]


# ── Uzman Sistemi Modelleri ──
class ExpertPreferencesRequest(BaseModel):
    primary_goal: str
    priority_muscles: List[str]


class ExpertCheckinRequest(BaseModel):
    checkin_type: str
    checkin_date: Optional[str] = None
    session_rpe: Optional[float] = None
    day_fatigue: Optional[float] = None
    recovery_feeling: Optional[float] = None
    completion_percentage: Optional[float] = None
    notes: Optional[str] = ""


class ExpertDomsReportInput(BaseModel):
    muscle_group: str
    severity: float
    notes: Optional[str] = ""


class ExpertDomsReportRequest(BaseModel):
    report_date: Optional[str] = None
    reports: List[ExpertDomsReportInput]


class ExpertEquipmentRequest(BaseModel):
    available_equipment: List[str]


class ExpertConstraintRequest(BaseModel):
    constraint_id: Optional[int] = None
    muscle_group: str
    constraint_type: str = "pain"
    severity: float
    notes: Optional[str] = ""
    started_on: Optional[str] = None
    resolved: bool = False


class ExpertGenerateProgramRequest(BaseModel):
    days_per_week: Optional[int] = None


class ExpertActivateProgramRequest(BaseModel):
    program_version_id: int


class ExpertMissedSessionRequest(BaseModel):
    session_id: str
    recovery_score: float
    program_version_id: Optional[int] = None


class ExpertRpeDataRequest(BaseModel):
    checkin_date: Optional[str] = None
    session_rpe: int
    notes: Optional[str] = ""


class ExpertGoalsDataRequest(BaseModel):
    primary_goal: str
    priority_muscles: List[str]
    priority_note: Optional[str] = ""


class ExpertDomsDataRequest(BaseModel):
    muscle_group: str
    severity: int
    notes: Optional[str] = ""


class ExpertDomsEntryUpdateRequest(BaseModel):
    severity: int
    notes: Optional[str] = ""


class ExpertGymDataRequest(BaseModel):
    gym_id: Optional[str] = None
    name: str
    equipment: List[str] = []
    is_default: bool = False


class ExpertEquipmentPreferencesRequest(BaseModel):
    preferred_equipment: List[str] = Field(default_factory=list)


class ExpertMovementPreferencesRequest(BaseModel):
    preferred_exercise_ids: List[str] = Field(default_factory=list)
    avoid_exercise_ids: List[str] = Field(default_factory=list)


class ExpertInjuryDataRequest(BaseModel):
    injury_id: Optional[str] = None
    area: str
    injury_type: str = "other"
    severity: int
    is_active: bool = True
    notes: Optional[str] = ""
    tingling_severity: Optional[int] = Field(
        None, ge=0, le=5, description="Sızlama ağrısı şiddeti (özellikle tendonlar için)"
    )


class ExpertLegacyResetRequest(BaseModel):
    confirmation: str


# ── Beslenme Modelleri ──
class NutritionLogSchema(BaseModel):
    username: str
    log_date: str = ""
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    notes: str = ""


class NutritionLogUpdateSchema(NutritionLogSchema):
    original_date: str
