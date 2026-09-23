"""Antrenman (Workout) kayıt, listeleme, silme ve güncelleme API uç noktaları."""
from fastapi import APIRouter, Body, Depends

from core.security import _resolve_current_user
from models.schemas import WorkoutCreate, WorkoutUpdate
from services.workout_service import (
    create_workout,
    delete_workout,
    get_workouts_by_user,
    update_workout,
)

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


@router.post("")
@router.post("/")
def save_workout(
    data: WorkoutCreate = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    return create_workout(user["id"], data.model_dump())


@router.get("")
@router.get("/")
def list_workouts(user: dict = Depends(_resolve_current_user)):
    return get_workouts_by_user(user["id"])


@router.delete("/{workout_id}")
def remove_workout(workout_id: int, user: dict = Depends(_resolve_current_user)):
    return delete_workout(workout_id, user["id"])


@router.put("/{workout_id}")
def edit_workout(
    workout_id: int,
    data: WorkoutUpdate = Body(...),
    user: dict = Depends(_resolve_current_user),
):
    update_payload = {k: v for k, v in data.model_dump().items() if v is not None}
    return update_workout(workout_id, update_payload, user["id"])
