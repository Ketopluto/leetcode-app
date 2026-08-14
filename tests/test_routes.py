import os

from app.models import Student


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "healthy"


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_admin_dashboard_requires_login(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]


def test_admin_students_requires_login(client):
    resp = client.get("/admin/students", follow_redirects=False)
    assert resp.status_code == 302


def test_admin_login_wrong_password(client):
    resp = client.post("/admin/login", data={"password": "wrong"}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid password" in resp.data


def test_admin_login_correct_password(client):
    resp = client.post(
        "/admin/login",
        data={"password": os.environ["HOD_PASSWORD"]},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin" in resp.headers["Location"]


def test_admin_login_rate_limited_after_five_attempts(client):
    for _ in range(5):
        client.post("/admin/login", data={"password": "wrong"})
    resp = client.post("/admin/login", data={"password": "wrong"})
    assert resp.status_code == 429


def test_admin_dashboard_after_login(admin_client):
    resp = admin_client.get("/admin")
    assert resp.status_code == 200


def test_download_csv_with_no_students(client):
    resp = client.get("/download")
    assert resp.status_code == 200
    assert resp.headers["Content-type"].startswith("text/csv")
    assert b"Roll Number" in resp.data


def test_api_stats_with_no_students(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["results"] == []


def test_student_profile_not_found(client):
    resp = client.get("/student/does-not-exist", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Student not found" in resp.data


def test_student_profile_higher_studies_skips_network_call(client, app):
    from app import db

    with app.app_context():
        student = Student(
            register_number="REG001",
            name="Test Student",
            leetcode_username="Higher Studies",
            year=4,
            section=None,
        )
        db.session.add(student)
        db.session.commit()

    resp = client.get("/student/REG001")
    assert resp.status_code == 200
