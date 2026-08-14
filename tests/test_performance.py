"""
Tests for the backend performance changes:
- student profile detail stats are cached (no live API call on repeat visits)
- a manual refresh writes through to that same cache
- the consolidated student/stats query returns the same shape as before
"""
import app.routes as routes_module
from app.models import Student, StudentStats


def make_counting_stub(total_solved=42):
    calls = []

    def stub(username):
        calls.append(username)
        return {
            "username": username,
            "totalSolved": total_solved,
            "easySolved": 20,
            "mediumSolved": 15,
            "hardSolved": 7,
            "totalSubmissions": [],
            "recentSubmissions": [],
            "ranking": 1000,
            "contributionPoint": 0,
            "reputation": 0,
            "acceptance_rate": 55.5,
            "profile_url": f"https://leetcode.com/u/{username}/",
        }

    stub.calls = calls
    return stub


def _add_student(app, db, register_number="REG100", username="realuser"):
    with app.app_context():
        student = Student(
            register_number=register_number,
            name="Cache Test",
            leetcode_username=username,
            year=2,
            section="A",
        )
        db.session.add(student)
        db.session.commit()


def test_student_profile_only_fetches_once_across_visits(client, app, monkeypatch):
    from app import db

    stub = make_counting_stub()
    monkeypatch.setattr(routes_module, "fetch_detailed_leetcode_stats", stub)
    _add_student(app, db)

    resp1 = client.get("/student/REG100")
    resp2 = client.get("/student/REG100")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(stub.calls) == 1, "second visit should be served from cache, not re-fetched"


def test_manual_refresh_writes_through_to_profile_cache(client, app, monkeypatch):
    from app import db

    stub = make_counting_stub(total_solved=42)
    monkeypatch.setattr(routes_module, "fetch_detailed_leetcode_stats", stub)
    _add_student(app, db)

    # Visit the profile first so the (stale) value gets cached.
    client.get("/student/REG100")
    assert len(stub.calls) == 1

    # Now the stub "improves" - simulate the student solving more problems -
    # and the user hits the manual refresh button.
    stub2 = make_counting_stub(total_solved=99)
    monkeypatch.setattr(routes_module, "fetch_detailed_leetcode_stats", stub2)

    refresh_resp = client.post("/api/refresh-student/REG100")
    assert refresh_resp.status_code == 200
    assert refresh_resp.get_json()["stats"]["total"] == 99
    assert len(stub2.calls) == 1

    # Reload the profile page - it should show the refreshed value from cache
    # (via the fresh stub's write-through), not trigger a second live fetch.
    resp = client.get("/student/REG100")
    assert resp.status_code == 200
    assert len(stub2.calls) == 1, "profile page should reuse the refreshed cache entry"


def test_load_students_with_cached_stats_matches_db(app):
    from app import db

    with app.app_context():
        student = Student(
            register_number="REG200",
            name="Query Test",
            leetcode_username="quser",
            year=3,
            section="B",
        )
        db.session.add(student)
        db.session.commit()

        stats = StudentStats(
            student_id=student.id,
            easy_solved=5,
            medium_solved=3,
            hard_solved=1,
            total_solved=9,
        )
        db.session.add(stats)
        db.session.commit()

        students, student_id_map, db_stats_map = routes_module.load_students_with_cached_stats()

        assert ("quser", "Query Test", "REG200", 3, "B") in students
        assert student_id_map["quser"] == student.id
        assert db_stats_map["quser"] == {
            "easy_solved": 5,
            "medium_solved": 3,
            "hard_solved": 1,
            "total_solved": 9,
        }


def test_download_csv_is_db_only_no_network(client, app, monkeypatch):
    """
    /download must never trigger a live LeetCode API call - it's a public,
    unauthenticated GET endpoint (see get_stats_from_db in routes.py). Assert
    it reads straight from StudentStats and never touches the live fetcher.
    """
    from app import db

    def explode(*args, **kwargs):
        raise AssertionError("/download must not call the live fetcher")

    monkeypatch.setattr(routes_module, "fetch_students_concurrent", explode)

    with app.app_context():
        student = Student(
            register_number="REG300",
            name="CSV Student",
            leetcode_username="csvuser",
            year=1,
            section="C",
        )
        db.session.add(student)
        db.session.commit()

        db.session.add(StudentStats(
            student_id=student.id,
            easy_solved=10,
            medium_solved=5,
            hard_solved=2,
            total_solved=17,
        ))
        db.session.commit()

    resp = client.get("/download")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "CSV Student" in body
    assert "csvuser" in body
    assert "17" in body


def test_api_student_stats_returns_db_values_no_network(client, app, monkeypatch):
    """
    The auto-refresh polling endpoint must be pure DB read - assert it works
    correctly even if the live fetcher would raise, proving it never calls it.
    """
    from app import db

    def explode(*args, **kwargs):
        raise AssertionError("api_student_stats must not call the live fetcher")

    monkeypatch.setattr(routes_module, "fetch_detailed_leetcode_stats", explode)

    with app.app_context():
        student = Student(
            register_number="REG400",
            name="Poll Test",
            leetcode_username="polluser",
            year=2,
            section=None,
        )
        db.session.add(student)
        db.session.commit()

        db.session.add(StudentStats(
            student_id=student.id,
            easy_solved=20,
            medium_solved=15,
            hard_solved=7,
            total_solved=42,
        ))
        db.session.commit()

    resp = client.get("/api/student-stats/REG400")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["stats"] == {"easy": 20, "medium": 15, "hard": 7, "total": 42}


def test_api_student_stats_defaults_to_zero_without_stats_row(client, app):
    from app import db

    with app.app_context():
        student = Student(
            register_number="REG401",
            name="No Stats Row",
            leetcode_username="nouser",
            year=1,
            section=None,
        )
        db.session.add(student)
        db.session.commit()

    resp = client.get("/api/student-stats/REG401")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["stats"] == {"easy": 0, "medium": 0, "hard": 0, "total": 0}


def test_api_student_stats_404_for_missing_student(client):
    resp = client.get("/api/student-stats/does-not-exist")
    assert resp.status_code == 404


def test_load_students_with_cached_stats_handles_no_stats_row(app):
    from app import db

    with app.app_context():
        student = Student(
            register_number="REG201",
            name="No Stats Yet",
            leetcode_username="nsuser",
            year=1,
            section=None,
        )
        db.session.add(student)
        db.session.commit()

        students, student_id_map, db_stats_map = routes_module.load_students_with_cached_stats()

        assert ("nsuser", "No Stats Yet", "REG201", 1, None) in students
        assert student_id_map["nsuser"] == student.id
        assert "nsuser" not in db_stats_map
