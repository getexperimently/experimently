"""
Authentication endpoints for the API.

Two providers share this router (selected by ``settings.AUTH_PROVIDER``):

* ``local`` (Community Edition default) — e-mail + password against the
  ``users`` table, HS256 JWTs issued by ``core.security``.  Endpoints:
  ``POST /login``, ``GET /me``, ``POST /logout`` and the OAuth2 form
  ``POST /token`` (``username`` = e-mail) so Swagger's *Authorize* works.
* ``cognito`` — AWS Cognito.  The legacy endpoints (signup, confirm, token,
  forgot/reset password, refresh, me) are unchanged; ``/login`` and
  ``/logout`` answer 404 because Cognito has its own flows.
"""

from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token, oauth2_scheme
from backend.app.models.user import User
from backend.app.schemas.auth import (
    SignUpRequest,
    SignUpResponse,
    ConfirmSignUpRequest,
    ConfirmSignUpResponse,
    TokenResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ConfirmForgotPasswordRequest,
    ConfirmForgotPasswordResponse,
    RefreshTokenRequest,
    UserInfoResponse,
    LoginRequest,
    LoginResponse,
    UserMe,
)
from backend.app.services.auth_service import CognitoAuthService
from backend.app.services.local_auth_service import (
    AccountLockedError,
    InvalidCredentialsError,
    local_auth_service,
)

router = APIRouter()

INVALID_CREDENTIALS_DETAIL = "Invalid email or password"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_local_provider() -> bool:
    return settings.AUTH_PROVIDER == "local"


def _require_local_provider() -> None:
    """404 for endpoints that only exist on the local provider."""
    if not _is_local_provider():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not available: AUTH_PROVIDER is not 'local'",
        )


def user_to_me(user: User) -> UserMe:
    """Serialise a ``User`` row into the ``UserMe`` contract shape."""
    return UserMe(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_superuser=bool(user.is_superuser),
        is_active=bool(user.is_active),
        auth_provider=settings.AUTH_PROVIDER,
    )


def _issue_local_login(db: Session, email: str, password: str) -> LoginResponse:
    """Authenticate with the local provider and build the token response."""
    try:
        user = local_auth_service.authenticate(db, email, password)
    except AccountLockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=(
                "Too many failed login attempts; account temporarily locked. "
                f"Retry in {exc.retry_after_seconds} seconds."
            ),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_local_access_token(user)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.LOCAL_AUTH_TOKEN_TTL_MINUTES * 60,
        user=user_to_me(user),
    )


# ---------------------------------------------------------------------------
# Local provider endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"description": INVALID_CREDENTIALS_DETAIL},
        423: {"description": "Account temporarily locked after repeated failures"},
    },
)
def login_local(body: LoginRequest, db: Session = Depends(deps.get_db)) -> Any:
    """
    Sign in with e-mail and password (``AUTH_PROVIDER=local``).

    Returns a bearer token plus the user's profile.  The same 401 message is
    used for an unknown address, a wrong password and an inactive account so
    the endpoint cannot be used to enumerate users.  After
    ``LOCAL_AUTH_MAX_FAILED_ATTEMPTS`` failures within
    ``LOCAL_AUTH_LOCKOUT_MINUTES`` the address answers 423 until the window
    expires.
    """
    _require_local_provider()
    return _issue_local_login(db, body.email, body.password)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_local() -> Response:
    """
    Sign out.

    Local tokens are stateless, so this endpoint exists for the client's
    benefit (it discards the token); nothing is revoked server-side.
    """
    _require_local_provider()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Cognito endpoints (unchanged) + provider-aware /token and /me
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=SignUpResponse, status_code=status.HTTP_201_CREATED)
def signup(signup_data: SignUpRequest) -> Any:
    """
    Register a new user.
    """
    auth_service = CognitoAuthService()
    try:
        response = auth_service.sign_up(
            username=signup_data.username,
            password=signup_data.password,
            email=signup_data.email,
            given_name=signup_data.given_name,
            family_name=signup_data.family_name,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/confirm", response_model=ConfirmSignUpResponse)
def confirm_signup(confirm_data: ConfirmSignUpRequest) -> Any:
    """
    Confirm user registration with the verification code.
    """
    auth_service = CognitoAuthService()
    try:
        response = auth_service.confirm_sign_up(
            username=confirm_data.username,
            confirmation_code=confirm_data.confirmation_code,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/token", response_model=Union[LoginResponse, TokenResponse])
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.

    With ``AUTH_PROVIDER=local`` the form's ``username`` field is the user's
    e-mail address and the response has the same shape as ``/login`` (this is
    what makes Swagger's *Authorize* button work).  With ``cognito`` the
    credentials are forwarded to the user pool.
    """
    if _is_local_provider():
        return _issue_local_login(db, form_data.username, form_data.password)

    auth_service = CognitoAuthService()
    try:
        response = auth_service.sign_in(
            username=form_data.username,
            password=form_data.password,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(forgot_password_data: ForgotPasswordRequest) -> Any:
    """
    Initiate the forgot password flow.
    """
    auth_service = CognitoAuthService()
    try:
        response = auth_service.forgot_password(
            username=forgot_password_data.username,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/reset-password", response_model=ConfirmForgotPasswordResponse)
def reset_password(reset_data: ConfirmForgotPasswordRequest) -> Any:
    """
    Complete the forgot password flow by setting a new password.
    """
    auth_service = CognitoAuthService()
    try:
        response = auth_service.confirm_forgot_password(
            username=reset_data.username,
            confirmation_code=reset_data.confirmation_code,
            new_password=reset_data.new_password,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(refresh_data: RefreshTokenRequest) -> Any:
    """
    Refresh the access token using a refresh token.
    """
    auth_service = CognitoAuthService()
    try:
        response = auth_service.refresh_token(
            refresh_token=refresh_data.refresh_token,
        )
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/me", response_model=Union[UserMe, UserInfoResponse])
def get_user_info(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    Get current user information.

    * ``AUTH_PROVIDER=local`` (or the dev-auth bypass): the ``UserMe`` profile
      of the bearer's user — ``{id, email, username, full_name, role,
      is_superuser, is_active, auth_provider}``.
    * ``AUTH_PROVIDER=cognito``: the Cognito ``{username, attributes}`` record.
    """
    if _is_local_provider() or deps.dev_auth_bypass_active():
        user = deps.get_current_active_user(deps.get_current_user(token=token, db=db))
        return user_to_me(user)

    cognito_token = deps.get_token(request)
    auth_service = CognitoAuthService()
    try:
        response = auth_service.get_user(access_token=cognito_token)
        return response
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
