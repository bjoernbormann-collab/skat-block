"""End-to-end web behaviour: login, guards, error pages."""

from __future__ import annotations

from app.db import session_scope
from app.models.auth import User
from app.models.enums import UserRole
from app.security import hash_password


def _make_user(username: str, password: str, role: str = UserRole.ADMIN.value) -> None:
    with session_scope() as db:
        db.add(User(username=username, full_name=username, role=role,
                    password_hash=hash_password(password)))


def test_health_endpoint_answers(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_dashboard_redirects_when_not_logged_in(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Anmelden" in response.text


def test_login_with_wrong_password_shows_a_german_message(client):
    _make_user("web-wrong", "richtiges-passwort")
    response = client.post("/login", data={"username": "web-wrong",
                                           "password": "falsch", "next": "/"})
    assert response.status_code == 401
    assert "Benutzername oder Passwort ist falsch." in response.text
    # No hint about which half was wrong, and no stack trace.
    assert "Traceback" not in response.text


def test_full_login_logout_cycle(client):
    _make_user("web-user", "ein-gutes-passwort")

    login = client.post("/login",
                        data={"username": "web-user", "password": "ein-gutes-passwort",
                              "next": "/"},
                        follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/"

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Übersicht" in dashboard.text
    assert "web-user" in dashboard.text

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_open_redirect_is_not_possible(client):
    """?next= must never bounce the user to another host."""
    _make_user("web-redirect", "ein-gutes-passwort")
    response = client.post("/login",
                           data={"username": "web-redirect",
                                 "password": "ein-gutes-passwort",
                                 "next": "https://beispiel.invalid/phish"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_unknown_page_shows_the_german_error_page(client):
    response = client.get("/gibt-es-nicht", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert "Nicht gefunden" in response.text
    assert "Traceback" not in response.text


def test_error_page_renders_for_a_logged_in_user(client):
    """Regression: the error page reads request.state.user after the request
    session has been rolled back and closed. Handing templates the ORM object
    made every friendly 400 explode into a 500 with a stack trace."""
    _make_user("web-error", "ein-gutes-passwort")
    client.post("/login", data={"username": "web-error",
                                "password": "ein-gutes-passwort", "next": "/"},
                follow_redirects=False)

    response = client.get("/artikel/999999", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert "Nicht gefunden" in response.text
    assert "web-error" in response.text, "Kopfzeile muss weiter gerendert werden"
    assert "Traceback" not in response.text
    assert "DetachedInstance" not in response.text


def test_session_cookie_is_httponly(client):
    _make_user("web-cookie", "ein-gutes-passwort")
    response = client.post("/login",
                           data={"username": "web-cookie",
                                 "password": "ein-gutes-passwort", "next": "/"},
                           follow_redirects=False)
    cookie_header = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
