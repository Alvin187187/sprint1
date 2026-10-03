"""Simple session auth (PRD §9: no enterprise SSO needed)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app import repository, telemetry
from app.deps import AdvisorDep, CurrentUser, SettingsDep
from app.schemas import AdvisorOut, LoginRequest, SessionOut, UserOut
from app.security import (
    SESSION_COOKIE,
    hash_session_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    advisor: AdvisorDep,
) -> SessionOut:
    user = await repository.get_user_by_email(payload.email.strip())
    # Hash-compare even when the user is missing so a wrong email and a wrong
    # password take the same time and are indistinguishable to a prober.
    stored_hash = user["password_hash"] if user else "scrypt$32768$8$1$AAAA$AAAA"
    ok = verify_password(payload.password, stored_hash)

    if not user or not ok:
        await telemetry.log_event(
            telemetry.LOGIN_FAILED,
            severity="warn",
            user_id=user["id"] if user else None,
            email=payload.email[:120],
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")

    token, token_hash = new_session_token()
    await repository.create_session(
        user["id"], token_hash, settings.session_ttl_hours, request.headers.get("user-agent")
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )
    await telemetry.log_event(telemetry.LOGIN_SUCCEEDED, user_id=user["id"])

    return SessionOut(
        user=UserOut(**{k: user[k] for k in ("id", "email", "display_name", "role")}),
        advisor=AdvisorOut(id=advisor["id"], name=advisor["name"]),
    )


@router.get("/me", response_model=SessionOut)
async def me(user: CurrentUser, advisor: AdvisorDep) -> SessionOut:
    return SessionOut(
        user=UserOut(**{k: user[k] for k in ("id", "email", "display_name", "role")}),
        advisor=AdvisorOut(id=advisor["id"], name=advisor["name"]),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await repository.revoke_session(hash_session_token(token))
    response.delete_cookie(SESSION_COOKIE, path="/")
