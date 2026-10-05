"""Authentication over HTTP: login, tokens and /me."""
from datetime import timedelta

import jwt

from tests.integration.conftest import SECRET, auth_headers, login


def test_login_with_valid_credentials_returns_a_bearer_token(client):
    response = login(client, "Ravi Kumar")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600


def test_login_with_a_wrong_password_is_rejected_with_a_generic_message(client):
    response = login(client, "Ravi Kumar", password="wrong")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_login_for_an_unknown_email_gives_the_same_response_as_a_wrong_password(client):
    unknown = client.post("/auth/login", json={"email": "nobody@example.invalid", "password": "x"})
    wrong = login(client, "Ravi Kumar", password="wrong")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_me_returns_the_profile_for_the_token_holder(client):
    response = client.get("/me", headers=auth_headers(client, "Arjun Rao"))

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["role"], body["status"]) == ("Arjun Rao", "manager", "confirmed")
    assert "password_hash" not in body


def test_me_requires_a_token(client):
    assert client.get("/me").status_code == 401


def test_a_tampered_token_is_rejected(client):
    token = login(client, "Ravi Kumar").json()["access_token"]
    forged = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_a_token_signed_with_another_secret_is_rejected(client, clock):
    forged = jwt.encode(
        {"sub": "1", "role": "hr_admin", "exp": clock.current + timedelta(hours=1)},
        "some-other-secret-" + "y" * 40,
        algorithm="HS256",
    )

    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_an_unsigned_token_is_rejected(client, clock):
    unsigned = jwt.encode(
        {"sub": "1", "role": "hr_admin", "exp": clock.current + timedelta(hours=1)},
        None,
        algorithm="none",
    )

    assert client.get("/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_an_expired_token_is_rejected(client, clock):
    headers = auth_headers(client, "Ravi Kumar")
    clock.advance(minutes=61)

    assert client.get("/me", headers=headers).status_code == 401


def test_the_role_comes_from_the_database_not_the_token(client, clock):
    # A token claiming to be hr_admin, correctly signed, for an employee-role user.
    token = jwt.encode(
        {"sub": "4", "role": "hr_admin", "exp": clock.current + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )

    body = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()

    assert body["role"] == "employee"


def test_passwords_are_stored_as_argon2_hashes(api_db):
    hashes = {r[0] for r in api_db.execute("SELECT password_hash FROM employees")}

    assert all(h.startswith("$argon2") for h in hashes)


def fail_login(client, name="Ravi Kumar", times=1):
    return [login(client, name, password="wrong") for _ in range(times)]


def test_five_failed_logins_lock_the_account_even_for_the_correct_password(client):
    responses = fail_login(client, times=5)
    locked = login(client, "Ravi Kumar")

    assert [r.status_code for r in responses] == [401] * 5
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert locked.json()["error"]["code"] == "http_429"


def test_the_account_unlocks_after_fifteen_minutes(client, clock):
    fail_login(client, times=5)
    clock.advance(minutes=15, seconds=1)

    assert login(client, "Ravi Kumar").status_code == 200


def test_the_account_stays_locked_before_the_lockout_ends(client, clock):
    fail_login(client, times=5)
    clock.advance(minutes=14)

    assert login(client, "Ravi Kumar").status_code == 429


def test_failures_older_than_ten_minutes_do_not_count(client, clock):
    fail_login(client, times=4)
    clock.advance(minutes=11)
    fail_login(client, times=1)

    assert login(client, "Ravi Kumar").status_code == 200


def test_a_successful_login_resets_the_failure_count(client):
    fail_login(client, times=4)
    assert login(client, "Ravi Kumar").status_code == 200
    fail_login(client, times=4)

    assert login(client, "Ravi Kumar").status_code == 200


def test_lockout_is_per_account(client):
    fail_login(client, "Ravi Kumar", times=5)

    assert login(client, "Divya Menon").status_code == 200


def test_unknown_emails_are_throttled_the_same_way(client):
    body = {"email": "ghost@example.invalid", "password": "x"}
    codes = [client.post("/auth/login", json=body).status_code for _ in range(6)]

    assert codes == [401, 401, 401, 401, 401, 429]
