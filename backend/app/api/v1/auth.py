"""Authentication endpoints: register, login, refresh, logout, and account
recovery (password reset, email verification, sign-in history)."""
from typing import List

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentTokenPayload, CurrentUser, DbSession
from app.api.rate_limit_deps import rate_limit_auth
from app.core.exceptions import AppError
from app.db.models.audit import AuditAction
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginHistoryEntry,
    LogoutRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    TokenPair,
    UserCreate,
    UserLogin,
    UserRead,
    VerifyEmailRequest,
)
from app.schemas.common import APIResponse
from app.services.account_service import get_account_service
from app.services.audit_service import get_audit_service
from app.services.auth_service import get_auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _client_ip(request: Request) -> str | None:
    """Caller IP, preferring the proxy's forwarded value when present."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post(
    "/register",
    response_model=APIResponse[UserRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
)
def register(payload: UserCreate, request: Request, db: DbSession) -> APIResponse[UserRead]:
    service = get_auth_service()
    user = service.register(db, payload)
    # Sent regardless of REQUIRE_EMAIL_VERIFICATION so the address can be
    # confirmed even while verification is optional.
    get_account_service().send_verification_email(db, user)
    get_audit_service().record(
        db,
        AuditAction.REGISTERED,
        user=user,
        ip_address=_client_ip(request),
        request_id=request.state.request_id,
    )
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="User registered successfully.",
        data=UserRead.model_validate(user),
    )


@router.post("/login", response_model=APIResponse[TokenPair], dependencies=[Depends(rate_limit_auth)])
def login(payload: UserLogin, request: Request, db: DbSession) -> APIResponse[TokenPair]:
    service = get_auth_service()
    audit = get_audit_service()
    ip_address, request_id = _client_ip(request), request.state.request_id

    try:
        user = service.authenticate(db, payload.email, payload.password)
    except AppError:
        # A failed attempt is the more interesting half of a login audit -
        # it is what makes credential stuffing visible. The email is recorded
        # because it was submitted, never the password or why it failed.
        audit.record(
            db,
            AuditAction.LOGIN_FAILED,
            user_email=payload.email,
            ip_address=ip_address,
            request_id=request_id,
        )
        raise

    tokens = service.issue_token_pair(user)
    audit.record(
        db, AuditAction.LOGIN_SUCCEEDED, user=user, ip_address=ip_address, request_id=request_id
    )
    return APIResponse.ok(request_id=request.state.request_id, message="Login successful.", data=tokens)


@router.post("/refresh", response_model=APIResponse[TokenPair])
def refresh(payload: RefreshTokenRequest, request: Request, db: DbSession) -> APIResponse[TokenPair]:
    service = get_auth_service()
    tokens = service.refresh(db, payload.refresh_token)
    return APIResponse.ok(request_id=request.state.request_id, message="Token refreshed.", data=tokens)


@router.get("/me", response_model=APIResponse[UserRead])
def get_current_user_profile(request: Request, user: CurrentUser) -> APIResponse[UserRead]:
    """The signed-in user's own profile, including their role.

    Lets the client render the correct navigation without guessing. It is
    not an authorization mechanism: the server re-checks the role on every
    protected route, so a client that lies about this gains nothing.
    """
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Profile retrieved.",
        data=UserRead.model_validate(user),
    )


@router.post(
    "/forgot-password",
    response_model=APIResponse[None],
    dependencies=[Depends(rate_limit_auth)],
)
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: DbSession
) -> APIResponse[None]:
    """Send a password reset link, if the address belongs to an account.

    Always reports success. Answering "no such user" would turn this into a
    free membership oracle - anyone could test addresses against it.
    """
    get_account_service().request_password_reset(db, payload.email, request.state.request_id)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="If that address has an account, a reset link has been sent.",
    )


@router.post(
    "/reset-password",
    response_model=APIResponse[None],
    dependencies=[Depends(rate_limit_auth)],
)
def reset_password(payload: ResetPasswordRequest, request: Request, db: DbSession) -> APIResponse[None]:
    """Set a new password using an emailed token, ending all sessions."""
    user = get_account_service().reset_password(db, payload.token, payload.new_password)
    get_audit_service().record(
        db,
        AuditAction.PASSWORD_RESET,
        user=user,
        ip_address=_client_ip(request),
        request_id=request.state.request_id,
    )
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Password updated. Existing sessions have been signed out.",
    )


@router.post("/verify-email", response_model=APIResponse[UserRead])
def verify_email(payload: VerifyEmailRequest, request: Request, db: DbSession) -> APIResponse[UserRead]:
    user = get_account_service().verify_email(db, payload.token)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Email address confirmed.",
        data=UserRead.model_validate(user),
    )


@router.post(
    "/resend-verification",
    response_model=APIResponse[None],
    dependencies=[Depends(rate_limit_auth)],
)
def resend_verification(request: Request, db: DbSession, user: CurrentUser) -> APIResponse[None]:
    """Re-send the confirmation link to the signed-in user's own address.

    Requires authentication, so it cannot be used to mail arbitrary people.
    """
    get_account_service().send_verification_email(db, user)
    return APIResponse.ok(
        request_id=request.state.request_id, message="Confirmation email sent if the address is unverified."
    )


@router.get("/login-history", response_model=APIResponse[List[LoginHistoryEntry]])
def login_history(request: Request, db: DbSession, user: CurrentUser) -> APIResponse[List[LoginHistoryEntry]]:
    """This account's own sign-in activity, most recent first.

    Reads the audit trail rather than keeping a second record of the same
    events, and is filtered to the caller - unlike the admin audit endpoint,
    which shows everyone.
    """
    events = get_audit_service().list_login_history(db, user_id=user.id, user_email=user.email)
    return APIResponse.ok(
        request_id=request.state.request_id,
        message="Login history retrieved.",
        data=[LoginHistoryEntry.model_validate(event) for event in events],
    )


@router.post("/logout", response_model=APIResponse[None])
def logout(
    payload: LogoutRequest,
    request: Request,
    db: DbSession,
    token_payload: CurrentTokenPayload,
) -> APIResponse[None]:
    service = get_auth_service()
    service.logout(db, token_payload, payload.refresh_token)
    get_audit_service().record(
        db,
        AuditAction.LOGOUT,
        user_id=token_payload.get("sub"),
        ip_address=_client_ip(request),
        request_id=request.state.request_id,
    )
    return APIResponse.ok(request_id=request.state.request_id, message="Logged out successfully.")
