import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app.main import app
from app.services.auth import StudioUser, get_current_user

USER = StudioUser(
    user_id="11111111-1111-4111-8111-111111111111",
    email="creator@example.test", role="creator",
)

def _client():
    app.dependency_overrides[get_current_user] = lambda: USER
    return TestClient(app)

def test_movie_script_returns_structured_story_and_storyboard(monkeypatch):
    import app.main as main
    payload = {"story":"СЦЕНА 1. НАТ. ЛЕС — ДЕНЬ\nГерой идёт по тропе.","storyboard":"Кадр 1: общий план, плавный наезд."}
    calls=[]; usage=[]
    monkeypatch.setattr(main,"_run_admitted_ai",lambda operation,user_id,call: calls.append((operation,user_id)) or SimpleNamespace(text=json.dumps(payload,ensure_ascii=False),actual_model="test-model"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: usage.append(k))
    c=_client()
    try:
        response=c.post("/api/movie/script",json={"title":"Лесная история","idea":"Путешествие девочки к старому маяку","genre":"Приключения","duration_minutes":5,"frame":"16:9","language":"Русский"})
        assert response.status_code==200
        assert response.json()["story"]==payload["story"]
        assert response.json()["storyboard"]==payload["storyboard"]
        assert response.json()["model"]=="test-model"
        assert calls[0][0]=="movie_script" and calls[0][1]==USER.user_id
        assert usage[0]["endpoint"]=="movie_script"
        assert response.headers["cache-control"]=="private, no-store"
    finally:
        app.dependency_overrides.clear()

def test_movie_script_rejects_invalid_ai_json_without_leaking_provider_output(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,"_run_admitted_ai",lambda *a,**k: SimpleNamespace(text="provider internal details",actual_model="test"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: None)
    c=_client()
    try:
        response=c.post("/api/movie/script",json={"title":"История","idea":"Короткое путешествие"})
        assert response.status_code==502
        assert "provider internal details" not in response.text
    finally:
        app.dependency_overrides.clear()

def test_movie_script_rejects_oversized_duration_and_unknown_fields():
    c=_client()
    try:
        too_long=c.post("/api/movie/script",json={"title":"История","idea":"Идея","duration_minutes":90})
        assert too_long.status_code==422
        extra=c.post("/api/movie/script",json={"title":"История","idea":"Идея","untrusted_price":0})
        assert extra.status_code==422
    finally:
        app.dependency_overrides.clear()

def test_movie_script_requires_authentication(monkeypatch):
    import app.services.auth as auth
    # Simulate a configured auth service but omit the bearer token. This
    # isolates the authentication contract from deployment configuration.
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(supabase_url="https://auth.example.test"))
    c=TestClient(app)
    response=c.post("/api/movie/script",json={"title":"История","idea":"Идея"})
    assert response.status_code == 401


def test_movie_director_returns_valid_ordered_scenes(monkeypatch):
    import app.main as main
    scenes = [
        {"scene_number":1,"title":"Пробуждение","location":"Комната","time_of_day":"Утро",
         "estimated_seconds":30,"characters":["Аня"],"action":"Героиня просыпается.",
         "visual_description":"Мягкий свет падает на лицо героини.",
         "camera_shots":["Общий план","Крупный план"],"lighting":"Мягкий утренний свет","transition":"Затемнение"},
        {"scene_number":2,"title":"Выход","location":"Улица","time_of_day":"Утро",
         "estimated_seconds":30,"characters":["Аня"],"action":"Аня выходит из дома.",
         "visual_description":"Героиня закрывает дверь и смотрит вдаль.",
         "camera_shots":["Средний план"],"lighting":"Естественный дневной свет","transition":"Склейка"}
    ]
    calls=[]; usage=[]
    monkeypatch.setattr(main,"_run_admitted_ai",lambda operation,user_id,call: calls.append(operation) or SimpleNamespace(text=json.dumps({"scenes":scenes},ensure_ascii=False),actual_model="director-test"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: usage.append(k))
    c=_client()
    try:
        response=c.post("/api/movie/director",json={"title":"Путь домой","story":"Аня просыпается и выходит из дома, чтобы начать путешествие.","duration_minutes":2})
        assert response.status_code==200
        assert [item["scene_number"] for item in response.json()["scenes"]]==[1,2]
        assert calls==["movie_director"]
        assert usage[0]["endpoint"]=="movie_director"
    finally:
        app.dependency_overrides.clear()


def test_movie_director_rejects_non_sequential_scene_numbers(monkeypatch):
    import app.main as main
    scene={"scene_number":2,"title":"Сцена","location":"Дом","time_of_day":"День",
           "estimated_seconds":30,"characters":[],"action":"Действие",
           "visual_description":"Описание","camera_shots":["Общий план"],
           "lighting":"Мягкий свет","transition":"Склейка"}
    monkeypatch.setattr(main,"_run_admitted_ai",lambda *a,**k: SimpleNamespace(text=json.dumps({"scenes":[scene]}),actual_model="test"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: None)
    c=_client()
    try:
        response=c.post("/api/movie/director",json={"title":"Фильм","story":"Это достаточно длинный сценарий для проверки структуры сцен."})
        assert response.status_code==502
    finally:
        app.dependency_overrides.clear()


def test_movie_director_requires_authentication(monkeypatch):
    import app.services.auth as auth
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(supabase_url="https://auth.example.test"))
    c=TestClient(app)
    response=c.post("/api/movie/director",json={"title":"Фильм","story":"Это достаточно длинный сценарий для проверки структуры сцен."})
    assert response.status_code==401


def test_movie_storyboard_returns_scene_matched_ordered_frames(monkeypatch):
    import app.main as main
    frames = [
        {"frame_number":1,"duration_seconds":4,"shot_type":"Общий план","camera_angle":"На уровне глаз",
         "camera_movement":"Медленный наезд","composition":"Героиня слева, маяк на горизонте.",
         "subject_focus":"Девочка на берегу","visual_prompt":"Кинематографичный широкий кадр девочки на берегу у маяка, мягкий рассветный свет.",
         "continuity_notes":"Красный шарф героини остаётся неизменным."},
        {"frame_number":2,"duration_seconds":3,"shot_type":"Крупный план","camera_angle":"Три четверти",
         "camera_movement":"Статичная камера","composition":"Лицо героини в центре кадра.",
         "subject_focus":"Взгляд героини","visual_prompt":"Крупный кинематографичный портрет девочки с красным шарфом на фоне моря.",
         "continuity_notes":"Сохранить красный шарф и направление взгляда."}
    ]
    result_scenes=[{"scene_number":1,"frames":frames}]
    calls=[]; usage=[]
    monkeypatch.setattr(main,"_run_admitted_ai",lambda operation,user_id,call: calls.append(operation) or SimpleNamespace(text=json.dumps({"scenes":result_scenes},ensure_ascii=False),actual_model="storyboard-test"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: usage.append(k))
    c=_client()
    scene={"scene_number":1,"title":"У маяка","location":"Берег моря","time_of_day":"Рассвет",
           "estimated_seconds":12,"characters":["Аня"],"action":"Аня смотрит на маяк.",
           "visual_description":"Девочка в красном шарфе стоит у моря.",
           "camera_shots":["Общий план"],"lighting":"Рассветный свет","transition":"Затемнение"}
    try:
        response=c.post("/api/movie/storyboard",json={"title":"Маяк","scenes":[scene],"frame":"16:9"})
        assert response.status_code==200
        assert len(response.json()["scenes"][0]["frames"])==2
        assert calls==["movie_storyboard"]
        assert usage[0]["endpoint"]=="movie_storyboard"
    finally:
        app.dependency_overrides.clear()


def test_movie_storyboard_rejects_frame_sequence_or_scene_mismatch(monkeypatch):
    import app.main as main
    frame={"frame_number":2,"duration_seconds":4,"shot_type":"Общий","camera_angle":"Спереди",
           "camera_movement":"Статика","composition":"Центр","subject_focus":"Героиня",
           "visual_prompt":"Героиня у моря в мягком свете.","continuity_notes":"Красный шарф."}
    monkeypatch.setattr(main,"_run_admitted_ai",lambda *a,**k: SimpleNamespace(text=json.dumps({"scenes":[{"scene_number":1,"frames":[frame]}]}),actual_model="test"))
    monkeypatch.setattr(main,"record_ai_usage",lambda *a,**k: None)
    c=_client()
    scene={"scene_number":1,"title":"Сцена","location":"Берег","time_of_day":"День",
           "estimated_seconds":10,"characters":[],"action":"Действие","visual_description":"Описание",
           "camera_shots":["Общий"],"lighting":"Свет","transition":"Склейка"}
    try:
        response=c.post("/api/movie/storyboard",json={"title":"Фильм","scenes":[scene]})
        assert response.status_code==502
    finally:
        app.dependency_overrides.clear()


def test_movie_storyboard_requires_authentication(monkeypatch):
    import app.services.auth as auth
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(supabase_url="https://auth.example.test"))
    c=TestClient(app)
    scene={"scene_number":1,"title":"Сцена","location":"Берег","time_of_day":"День",
           "estimated_seconds":10,"characters":[],"action":"Действие","visual_description":"Описание",
           "camera_shots":["Общий"],"lighting":"Свет","transition":"Склейка"}
    response=c.post("/api/movie/storyboard",json={"title":"Фильм","scenes":[scene]})
    assert response.status_code==401
