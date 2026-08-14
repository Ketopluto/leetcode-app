"""
Tests for /admin/sync-batch - the batched roster sync behind the admin sync
console. Covers the auth gate, batch walking, and delta reporting.
"""
import app.routes as routes_module
from app.models import Student, StudentStats


def _add_students(app, db, specs):
    """specs: [(register_number, username, stored_total or None), ...]"""
    with app.app_context():
        for i, (reg, username, stored) in enumerate(specs):
            student = Student(
                register_number=reg,
                name=f"Student {reg}",
                leetcode_username=username,
                year=3,
                section="A",
            )
            db.session.add(student)
            db.session.flush()
            if stored is not None:
                db.session.add(StudentStats(student_id=student.id, total_solved=stored))
        db.session.commit()


def _fake_fetch(totals):
    """Stub fetch_students_concurrent returning `totals` keyed by username."""
    async def fetch(students_to_fetch, cached_stats_map=None, concurrency=None):
        results = []
        for item in students_to_fetch:
            username = item[0]
            total = totals.get(username)
            if total is None:
                continue  # simulates a student no source could resolve
            results.append({
                "username": username,
                "easy": total, "medium": 0, "hard": 0, "total": total,
                "fetch_error": None, "is_stale": False,
            })
        return results
    return fetch


def test_sync_batch_requires_admin(client, app):
    from app import db
    _add_students(app, db, [("R1", "alpha", 10)])

    resp = client.post("/admin/sync-batch", json={"offset": 0})
    assert resp.status_code == 403


def test_sync_batch_reports_delta_against_stored_total(admin_client, app, monkeypatch):
    from app import db
    _add_students(app, db, [("R1", "alpha", 10)])
    monkeypatch.setattr(routes_module, "fetch_students_concurrent", _fake_fetch({"alpha": 17}))

    resp = admin_client.post("/admin/sync-batch", json={"offset": 0})
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["success"] is True
    row = body["results"][0]
    assert row["total"] == 17
    assert row["delta"] == 7
    assert row["status"] == "gained"

    # The new total must be persisted, not just reported.
    with app.app_context():
        student = Student.query.filter_by(register_number="R1").first()
        assert StudentStats.query.filter_by(student_id=student.id).first().total_solved == 17


def test_sync_batch_marks_unchanged_and_unreachable(admin_client, app, monkeypatch):
    from app import db
    _add_students(app, db, [("R1", "alpha", 10), ("R2", "ghost", 5)])
    # "ghost" is absent from the stub's results, i.e. no source resolved it.
    monkeypatch.setattr(routes_module, "fetch_students_concurrent", _fake_fetch({"alpha": 10}))

    body = admin_client.post("/admin/sync-batch", json={"offset": 0}).get_json()
    by_user = {r["username"]: r for r in body["results"]}

    assert by_user["alpha"]["status"] == "synced"
    assert by_user["alpha"]["delta"] == 0
    assert by_user["ghost"]["status"] == "unreachable"
    assert by_user["ghost"]["delta"] is None
    # An unreachable student keeps their last known total rather than zeroing.
    assert by_user["ghost"]["total"] == 5


def test_sync_batch_walks_roster_then_stops(admin_client, app, monkeypatch):
    from app import db
    specs = [(f"R{i}", f"user{i}", 0) for i in range(10)]
    _add_students(app, db, specs)
    monkeypatch.setattr(
        routes_module, "fetch_students_concurrent",
        _fake_fetch({f"user{i}": i for i in range(10)})
    )

    seen, offset, guard = [], 0, 0
    while offset is not None and guard < 20:
        body = admin_client.post("/admin/sync-batch", json={"offset": offset}).get_json()
        seen.extend(r["username"] for r in body["results"])
        assert body["total"] == 10
        offset = body["next_offset"]
        guard += 1

    # Every student visited exactly once, and the walk terminates.
    assert sorted(seen) == sorted(f"user{i}" for i in range(10))
    assert offset is None


def test_sync_batch_clamps_oversized_limit(admin_client, app, monkeypatch):
    from app import db
    specs = [(f"R{i}", f"user{i}", 0) for i in range(40)]
    _add_students(app, db, specs)
    monkeypatch.setattr(
        routes_module, "fetch_students_concurrent",
        _fake_fetch({f"user{i}": 1 for i in range(40)})
    )

    body = admin_client.post("/admin/sync-batch", json={"offset": 0, "limit": 9999}).get_json()
    assert len(body["results"]) <= routes_module.SYNC_BATCH_MAX
