"""Two-step sign-in (authenticator app + recovery codes) and passkeys, with a small software authenticator."""
import base64
import hashlib
import json
import struct
import time

import cbor2
import pyotp
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.modules.auth import two_step
from app.modules.auth.models import User
from tests.conftest import signup


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def current_code(secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).generate_otp(int(time.time()) // 30 + offset)


def enable(client, auth) -> tuple[str, list[str]]:
    setup = client.post("/api/auth/two-step/setup", headers=auth.headers).json()
    assert setup["uri"].startswith("otpauth://totp/") and "<svg" in setup["qr_svg"]
    r = client.post("/api/auth/two-step/enable", headers=auth.headers, json={"code": current_code(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


def login(client, email="owner@example.com", password="secret123"):
    client.cookies.clear()
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ------------------------------------------------------------------ authenticator app
def test_switching_the_app_on_needs_a_right_code(client, auth):
    setup = client.post("/api/auth/two-step/setup", headers=auth.headers).json()
    r = client.post("/api/auth/two-step/enable", headers=auth.headers, json={"code": "000000"})
    assert r.status_code == 400 and r.json()["code"] == "bad_code"
    assert client.get("/api/auth/security", headers=auth.headers).json()["two_step"] is False
    r = client.post("/api/auth/two-step/enable", headers=auth.headers, json={"code": current_code(setup["secret"])})
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 11 and c[5] == "-" for c in codes)
    security = client.get("/api/auth/security", headers=auth.headers).json()
    assert security["two_step"] is True and security["recovery_codes_left"] == 10
    assert client.post("/api/auth/two-step/setup", headers=auth.headers).status_code == 400  # already on


def test_sign_in_asks_for_the_code_and_each_code_works_once(client, auth, db):
    secret, _codes = enable(client, auth)
    db.get(User, auth.user_id).totp_last_step = None  # the code used to switch it on would otherwise count
    r = login(client)
    body = r.json()
    assert r.status_code == 200 and body["two_step"] is True and "access_token" not in body
    assert "sai_access" not in r.cookies  # no session before the code
    assert client.post("/api/auth/login/two-step", json={"challenge": body["challenge"], "code": "123456"}).status_code == 400

    code = current_code(secret)
    r = client.post("/api/auth/login/two-step", json={"challenge": body["challenge"], "code": code})
    assert r.status_code == 200 and r.json()["me"]["user"]["id"] == auth.user_id
    # the same code a second time (someone who saw it) is refused
    r = client.post("/api/auth/login/two-step", json={"challenge": login(client).json()["challenge"], "code": code})
    assert r.status_code == 400 and r.json()["code"] == "bad_code"


def test_recovery_codes_work_once_each(client, auth):
    _secret, codes = enable(client, auth)
    challenge = login(client).json()["challenge"]
    r = client.post("/api/auth/login/two-step", json={"challenge": challenge, "code": codes[0].upper()})
    assert r.status_code == 200
    r = client.post("/api/auth/login/two-step", json={"challenge": login(client).json()["challenge"], "code": codes[0]})
    assert r.status_code == 400
    assert client.get("/api/auth/security", headers=auth.headers).json()["recovery_codes_left"] == 9


def test_challenge_dies_when_the_account_signs_out_everywhere(client, auth, db):
    secret, _codes = enable(client, auth)
    challenge = login(client).json()["challenge"]
    db.get(User, auth.user_id).token_version += 1
    db.flush()
    r = client.post("/api/auth/login/two-step", json={"challenge": challenge, "code": current_code(secret, 1)})
    assert r.status_code == 401 and r.json()["code"] == "two_step_expired"


def test_a_reset_link_does_not_skip_the_phone(client, auth, db):
    from app.core.security import create_purpose_token

    enable(client, auth)
    user = db.get(User, auth.user_id)
    token = create_purpose_token("reset", f"{user.id}:{user.token_version}", hours=1)
    client.cookies.clear()
    r = client.post("/api/auth/password/reset", json={"token": token, "password": "brand-new-pass"})
    assert r.status_code == 200 and r.json()["two_step"] is True and "access_token" not in r.json()


def test_switching_off_needs_the_password_and_a_code(client, auth, db):
    secret, _codes = enable(client, auth)
    db.get(User, auth.user_id).totp_last_step = None
    r = client.post("/api/auth/two-step/disable", headers=auth.headers, json={"password": "wrong", "code": current_code(secret)})
    assert r.status_code == 400 and r.json()["code"] == "bad_password"
    r = client.post("/api/auth/two-step/disable", headers=auth.headers, json={"password": "secret123", "code": current_code(secret)})
    assert r.status_code == 200 and r.json()["two_step"] is False
    assert login(client).json()["me"]["user"]["id"] == auth.user_id  # back to the password alone


def test_new_recovery_codes_replace_the_old_ones(client, auth, db):
    secret, old = enable(client, auth)
    db.get(User, auth.user_id).totp_last_step = None
    new = client.post("/api/auth/two-step/recovery", headers=auth.headers, json={"code": current_code(secret)}).json()
    assert set(new["recovery_codes"]).isdisjoint(old)
    r = client.post("/api/auth/login/two-step", json={"challenge": login(client).json()["challenge"], "code": old[1]})
    assert r.status_code == 400


def test_platform_admin_can_reset_a_lost_phone(client, auth, db):
    admin = signup(client, email="root@example.com", name="Root", workspace="Platform")
    db.get(User, admin.user_id).is_superadmin = True
    db.flush()
    enable(client, auth)
    assert client.get("/api/admin/users", headers=admin.headers).json()["items"][-1]["two_step"] is True
    assert client.post(f"/api/admin/users/{auth.user_id}/reset-two-step", headers=auth.headers).status_code == 403
    r = client.post(f"/api/admin/users/{auth.user_id}/reset-two-step", headers=admin.headers)
    assert r.status_code == 200 and r.json()["two_step"] is False
    assert client.get("/api/auth/me", headers=auth.headers).status_code == 401  # signed out everywhere
    assert "me" in login(client).json()


# ------------------------------------------------------------------ passkeys
class SoftAuthenticator:
    """Just enough of a platform authenticator (ES256, no attestation) to exercise the server."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = b"cred-" + struct.pack(">Q", int(time.time() * 1e6))
        self.count = 0

    def _cose(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def create(self, options: dict, origin: str) -> dict:
        client_data = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origin}).encode()
        auth_data = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x45]) + struct.pack(">I", 0)
                     + bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose())
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64(client_data), "attestationObject": b64(attestation),
                             "transports": ["internal"]}, "clientExtensionResults": {}}

    def get(self, options: dict, origin: str, user_handle: bytes) -> dict:
        self.count += 1
        client_data = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origin}).encode()
        auth_data = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x05]) + struct.pack(">I", self.count)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.credential_id), "rawId": b64(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64(client_data), "authenticatorData": b64(auth_data),
                             "signature": b64(signature), "userHandle": b64(user_handle)},
                "clientExtensionResults": {}}


def register(client, auth, device: SoftAuthenticator, name="iPhone"):
    _rp, origin = two_step.relying_party()
    start = client.post("/api/auth/passkeys/register", headers=auth.headers).json()
    assert start["options"]["authenticatorSelection"]["residentKey"] == "required"
    return client.post("/api/auth/passkeys/register/verify", headers=auth.headers,
                       json={"token": start["token"], "credential": device.create(start["options"], origin), "name": name})


def passkey_login(client, device: SoftAuthenticator, user_id: int):
    _rp, origin = two_step.relying_party()
    client.cookies.clear()
    start = client.post("/api/auth/passkeys/login").json()
    credential = device.get(start["options"], origin, f"sai-{user_id}".encode())
    return client.post("/api/auth/passkeys/login/verify", json={"token": start["token"], "credential": credential}), start, credential


def test_passkey_signs_in_without_a_password_or_a_code(client, auth):
    enable(client, auth)  # even with the app on: a passkey is already two factors
    device = SoftAuthenticator()
    r = register(client, auth, device)
    assert r.status_code == 200, r.text
    assert [p["name"] for p in r.json()["passkeys"]] == ["iPhone"]
    # the same device cannot be added twice
    assert register(client, auth, device).status_code == 400

    r, start, credential = passkey_login(client, device, auth.user_id)
    assert r.status_code == 200, r.text
    assert r.json()["me"]["user"]["id"] == auth.user_id and "sai_access" in r.cookies
    # the signed answer cannot be replayed
    r = client.post("/api/auth/passkeys/login/verify", json={"token": start["token"], "credential": credential})
    assert r.status_code == 400 and r.json()["code"] == "passkey_expired"


def test_an_unknown_or_forged_passkey_is_refused(client, auth):
    known, stranger = SoftAuthenticator(), SoftAuthenticator()
    register(client, auth, known)
    r, _start, _credential = passkey_login(client, stranger, auth.user_id)
    assert r.status_code == 401 and r.json()["code"] == "passkey_unknown"
    # right credential id, wrong key (a copied id is not enough)
    stranger.credential_id = known.credential_id
    r, _start, _credential = passkey_login(client, stranger, auth.user_id)
    assert r.status_code == 401 and r.json()["code"] == "passkey_failed"


def test_passkeys_can_be_renamed_and_removed_only_by_their_owner(client, auth):
    other = signup(client, email="other@example.com", name="Other", workspace="Other")
    passkey_id = register(client, auth, SoftAuthenticator()).json()["passkeys"][0]["id"]
    assert client.patch(f"/api/auth/passkeys/{passkey_id}", headers=other.headers, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/auth/passkeys/{passkey_id}", headers=other.headers).status_code == 404
    r = client.patch(f"/api/auth/passkeys/{passkey_id}", headers=auth.headers, json={"name": "MacBook"})
    assert r.json()["passkeys"][0]["name"] == "MacBook"
    assert client.delete(f"/api/auth/passkeys/{passkey_id}", headers=auth.headers).json()["passkeys"] == []


# ------------------------------------------------------------------ platform AI keys: connection test
def test_platform_ai_key_test_says_whether_the_key_works(client, auth, db, mock_http):
    from app.modules.billing import platform

    admin = signup(client, email="root@example.com", name="Root", workspace="Platform")
    db.get(User, admin.user_id).is_superadmin = True
    db.flush()
    assert client.post("/api/admin/settings/ai/openai/test", headers=admin.headers).json()["code"] == "no_key"
    client.put("/api/admin/settings", headers=admin.headers, json={"values": {"ai.openai_api_key": "sk-good"}})
    assert client.post("/api/admin/settings/ai/openai/test", headers=auth.headers).status_code == 403

    def handler(method, url, kw):
        assert url == "https://api.openai.com/v1/models" and method == "GET"
        if kw["headers"]["Authorization"] == "Bearer sk-good":
            return mock_http.response(200, {"data": [{"id": "gpt-5-mini"}, {"id": "gpt-image-1"}]})
        return mock_http.response(401, {"error": {"message": "Incorrect API key provided."}})

    mock_http(handler)
    r = client.post("/api/admin/settings/ai/openai/test", headers=admin.headers).json()
    assert r["ok"] is True and r["models"] == 2
    assert client.get("/api/admin/settings", headers=admin.headers).json()["ai_status"]["openai"]["ok"] is True
    # a new key forgets the old result until it is tested
    client.put("/api/admin/settings", headers=admin.headers, json={"values": {"ai.openai_api_key": "sk-bad"}})
    assert "openai" not in client.get("/api/admin/settings", headers=admin.headers).json()["ai_status"]
    r = client.post("/api/admin/settings/ai/openai/test", headers=admin.headers).json()
    assert r["ok"] is False and "Incorrect API key" in r["message"]
    assert platform.get_setting(db, "ai.status.openai")["ok"] is False
