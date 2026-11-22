from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str = Field(min_length=1, max_length=120)
    locale: str = "ar"
    invitation_token: str | None = None


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)  # the e-mail, or the username
    password: str
    code: str | None = Field(default=None, max_length=20)  # two-step code, when the app already asks for it


class TwoFactorOut(BaseModel):
    """Answer of /login when the account has two-step sign-in: send the code with the challenge to /login/2fa."""

    two_factor_required: bool = True
    challenge: str


class TwoFactorLoginIn(BaseModel):
    challenge: str
    code: str = Field(min_length=6, max_length=20)  # 6 digits, or a recovery code


class RefreshIn(BaseModel):
    refresh_token: str | None = None  # mobile sends it; the web uses the cookie


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MembershipOut(BaseModel):
    workspace_id: int
    workspace_name: str
    role: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str | None = None
    name: str
    locale: str
    timezone: str
    avatar_url: str | None = None
    is_superadmin: bool = False
    email_verified: bool = False
    must_change_password: bool = False
    totp_enabled: bool = False


class ImpersonatorOut(BaseModel):
    """The platform administrator viewing the app as this user (the web shows a banner)."""

    id: int
    name: str
    email: str
    expires_at: datetime | None = None


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[MembershipOut]
    current_workspace_id: int | None
    impersonator: ImpersonatorOut | None = None


class SessionOut(TokensOut):
    me: MeOut


class MeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    username: str | None = Field(default=None, max_length=30)  # "" clears it
    locale: str | None = None
    timezone: str | None = None
    avatar_url: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class EmailChange(BaseModel):
    email: EmailStr
    password: str


class TokenIn(BaseModel):
    token: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
