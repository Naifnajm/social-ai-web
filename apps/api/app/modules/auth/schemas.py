from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str = Field(min_length=1, max_length=120)
    locale: str = "ar"
    invitation_token: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


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
    name: str
    locale: str
    timezone: str
    avatar_url: str | None = None
    is_superadmin: bool = False


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[MembershipOut]
    current_workspace_id: int | None


class SessionOut(TokensOut):
    me: MeOut


class MeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    locale: str | None = None
    timezone: str | None = None
    avatar_url: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)
