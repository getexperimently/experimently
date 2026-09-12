from typing import Generator, Optional, Union, Any, Dict
from uuid import UUID
import asyncio
from fastapi import Depends, HTTPException, status, Header, Request, Query
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel, SecretStr

from backend.app.core.config import settings
from backend.app.core.pagination import Paginator
from backend.app.core.security import (
    oauth2_scheme,
    hash_api_key,
    decode_local_token,
    InvalidTokenError,
)
from backend.app.core.permissions import ResourceType, Action, check_permission, check_ownership, get_permission_error_message
from backend.app.core.cognito import map_cognito_groups_to_role, should_be_superuser
from backend.app.db.session import SessionLocal
from backend.app.models.user import User, UserRole
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlag
from backend.app.models.report import Report
from backend.app.services.auth_service import auth_service
from loguru import logger
from backend.app.models.api_key import APIKey

# Try to import Redis, handle gracefully if not installed
try:
    import redis.asyncio as redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

    # Create a dummy redis class to avoid None.Redis error
    class redis:
        class Redis:
            pass


# OAuth2 scheme for token authentication
# oauth2_scheme is imported from backend.app.core.security.
# Do NOT redefine here — the imported version has auto_error=False so that a
# missing token reaches get_current_user (dev bypass vs. 401 is decided there).

# API key header extraction
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


# Cache control model
class CacheControl(BaseModel):
    """Cache control settings."""

    enabled: bool = False
    skip: bool = False
    redis: Optional[object] = None


# Redis pool
_redis_pool = None


async def get_redis_pool():
    """Get Redis connection pool."""
    global _redis_pool
    if not REDIS_AVAILABLE:
        logger.warning("Redis not available, cache disabled")
        return None

    if _redis_pool is None:
        try:
            _redis_pool = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
            )
        except Exception as e:
            logger.error(f"Redis connection error: {e}")
            return None
    return _redis_pool


async def get_db() -> Generator[Session, None, None]:
    """
    Get database session.

    Yields:
        Session: Database session
    """
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


def get_token(request: Request) -> str:
    """
    Extract the access token from the Authorization header.

    Args:
        request (Request): FastAPI request object

    Returns:
        str: Access token

    Raises:
        HTTPException: If the token is not found
    """
    authorization = request.headers.get("Authorization")

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


DEV_BYPASS_USERNAME = "dev-admin"
DEV_BYPASS_EMAIL = "dev@localhost"


def dev_auth_bypass_active() -> bool:
    """
    True only when the dev-admin bypass is enabled *and* permitted.

    Both conditions are read from ``settings`` at call time so tests can
    toggle them, and both must hold: ``DEV_AUTH_BYPASS`` must be exactly
    ``True`` and ``ENVIRONMENT`` must be ``development`` or ``test``.  No
    other environment variable (``TESTING``, ``DEBUG`` ...) unlocks it.
    """
    # ``is True`` also guards against a mocked settings object, whose
    # attribute would be a truthy MagicMock.
    return getattr(settings, "dev_auth_bypass_active", False) is True


def _get_or_create_dev_user(db: Session) -> User:
    """Return the synthetic dev-admin user used by the dev-auth bypass."""
    user = db.query(User).filter(User.username == DEV_BYPASS_USERNAME).first()
    if not user:
        user = User(
            username=DEV_BYPASS_USERNAME,
            email=DEV_BYPASS_EMAIL,
            full_name="Dev Admin",
            hashed_password="not-a-real-hash",
            is_active=True,
            role=UserRole.ADMIN,
            is_superuser=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authenticate_local_token(token: str, db: Session) -> User:
    """
    Resolve a locally issued JWT to its ``User`` row.

    401 for any decode/lookup failure, 400 when the account is inactive.
    """
    try:
        claims = decode_local_token(token)
        user_id = UUID(str(claims.get("sub")))
    except (InvalidTokenError, ValueError, TypeError) as exc:
        logger.debug(f"Local token rejected: {exc}")
        raise _credentials_exception()

    try:
        user = db.query(User).filter(User.id == user_id).first()
    except Exception as exc:  # pragma: no cover - defensive; DB errors are not auth errors
        logger.error(f"User lookup failed during local token auth: {exc}")
        raise _credentials_exception()

    if user is None:
        raise _credentials_exception()
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """
    Get the current authenticated user from the provided bearer token.

    Resolution order:

    1. Dev-admin bypass (``DEV_AUTH_BYPASS=true`` **and** ``ENVIRONMENT`` in
       development/test): returns the synthetic ``dev-admin`` superuser.
    2. No token: 401.
    3. ``AUTH_PROVIDER=local``: decode the HS256 JWT issued by
       ``/api/v1/auth/login`` and load the user by id (401 on any failure,
       400 if the account is inactive).
    4. ``AUTH_PROVIDER=cognito``: validate the token with Cognito and sync the
       user's role from its groups (unchanged legacy path).

    Args:
        token (str): Bearer access token (may be None)
        db (Session): Database session

    Returns:
        User: Current authenticated user

    Raises:
        HTTPException: If authentication fails
    """
    if dev_auth_bypass_active():
        try:
            return _get_or_create_dev_user(db)
        except Exception as dev_err:
            logger.error(f"Dev user creation failed: {dev_err}")
            raise HTTPException(status_code=500, detail=f"Dev auth error: {dev_err}")

    if not token:
        raise _credentials_exception("Not authenticated")

    if settings.AUTH_PROVIDER == "local":
        return _authenticate_local_token(token, db)

    try:
        # Get user details and groups from Cognito
        user_data = auth_service.get_user_with_groups(token)

        # Get user from database
        username = user_data.get("username")
        user = db.query(User).filter(User.username == username).first()

        # Extract groups and map to role
        cognito_groups = user_data.get("groups", [])

        # Map Cognito groups to role
        role = map_cognito_groups_to_role(cognito_groups)

        # Determine superuser status from Cognito admin groups
        is_superuser = should_be_superuser(cognito_groups)

        # If superuser, ensure they have ADMIN role for full permissions
        if is_superuser and role != UserRole.ADMIN:
            role = UserRole.ADMIN
            logger.info(f"User {username} is a superuser, assigning ADMIN role")

        if not user:
            # Create user in database if not exists
            email = user_data.get("attributes", {}).get("email")
            full_name = (
                f"{user_data.get('attributes', {}).get('given_name', '')} "
                f"{user_data.get('attributes', {}).get('family_name', '')}"
            ).strip()

            user = User(
                username=username,
                email=email,
                full_name=full_name,
                is_active=True,
                role=role,
                is_superuser=is_superuser
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            logger.info(f"Created new user {username} with role {role} and superuser={is_superuser}")
        elif settings.SYNC_ROLES_ON_LOGIN:
            # Update user's role and superuser status if changed
            role_changed = user.role != role
            superuser_changed = user.is_superuser != is_superuser

            if role_changed or superuser_changed:
                # Update user properties
                if role_changed:
                    user.role = role
                    logger.info(f"User {username} role updated to {role} based on Cognito groups")

                if superuser_changed:
                    user.is_superuser = is_superuser
                    logger.info(f"User {username} superuser status updated to {is_superuser}")

                # Commit changes to database
                db.commit()
                db.refresh(user)

        return user
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Get the current active user.

    Args:
        current_user (User): Current user

    Returns:
        User: Current active user

    Raises:
        HTTPException: If the user is inactive
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Get the current superuser.

    Args:
        current_user (User): Current active user

    Returns:
        User: Current superuser

    Raises:
        HTTPException: If the user is not a superuser
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


def get_current_superuser_or_none(
    current_user: User = Depends(get_current_active_user),
) -> Optional[User]:
    """
    Get current superuser or None.

    Args:
        current_user: Current authenticated user

    Returns:
        User: Current user if they are a superuser, None otherwise
    """
    if current_user.is_superuser:
        return current_user
    return None


def get_experiment_access(
    experiment: Union[Experiment, Dict[str, Any]],
    current_user: User = Depends(get_current_active_user)
) -> Union[Experiment, Dict[str, Any]]:
    """
    Check if user has access to the experiment.

    This function ensures the current user has permission to access
    the specified experiment, checking superuser status, permissions,
    and ownership as needed.

    Called directly from endpoints (positional `experiment` arg). For the
    dependency-injection variant that fetches the experiment from a path
    parameter, callers should use `Depends(get_experiment_by_key)` and pass
    the resolved experiment to this function.

    Args:
        experiment: The experiment to check access for
        current_user: The current authenticated user

    Returns:
        The experiment if access is allowed

    Raises:
        HTTPException: If the user does not have permission to access the experiment
    """
    # Superusers always have access
    if current_user.is_superuser:
        return experiment

    # Check if user has permission to read experiments
    if not check_permission(current_user, ResourceType.EXPERIMENT, Action.READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.EXPERIMENT, Action.READ),
        )

    # Check ownership for non-admin users for modification actions
    if not check_permission(current_user, ResourceType.EXPERIMENT, Action.UPDATE) and not check_ownership(current_user, experiment):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this experiment",
        )

    return experiment


def get_api_key(
    db: Session = Depends(get_db), api_key_header: str = Depends(API_KEY_HEADER)
) -> Optional[User]:
    """
    Validate API key from header and return associated user if valid.

    Args:
        db: Database session
        api_key_header: API key from header

    Returns:
        User: User associated with the API key

    Raises:
        HTTPException: If API key is invalid or inactive
    """
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key missing",
            headers={"WWW-Authenticate": "APIKey"},
        )

    # Look up by hashed key only. API keys must never be stored as plaintext.
    api_key_hash = hash_api_key(api_key_header)
    api_key = db.query(APIKey).filter(APIKey.key == api_key_hash).first()
    if not api_key or not api_key.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"},
        )

    # Get associated user
    user = db.query(User).filter(User.id == api_key.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"},
        )

    return user


def get_experiment_by_key(
    experiment_key: str,
    db: Session = Depends(get_db),
    required_status: Optional[ExperimentStatus] = None
) -> Experiment:
    """
    Get experiment by key or ID.

    Args:
        experiment_key (str): Experiment key or ID
        db (Session): Database session
        required_status (Optional[ExperimentStatus]): If provided, the experiment must have this status

    Returns:
        Experiment: Experiment with the given key or ID

    Raises:
        HTTPException: If experiment not found or has incorrect status
    """
    experiment = None

    # First try to lookup by ID (UUID)
    try:
        from uuid import UUID
        experiment_id = UUID(experiment_key)
        experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    except (ValueError, TypeError):
        # Not a valid UUID, try the original lookup method
        pass

    # If not found by ID, try the original lookup method
    if not experiment:
        experiment = (
            db.query(Experiment)
            .filter(getattr(Experiment, "key", None) == experiment_key)
            .first()
        )

    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # Check for required status if specified
    if required_status is not None and hasattr(experiment, 'status') and experiment.status != required_status:
        raise HTTPException(status_code=400, detail=f"Experiment not in {required_status.value} status")
    # Default check for active status (only if required_status is not specified)
    elif required_status is None and hasattr(experiment, 'status') and experiment.status != ExperimentStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Inactive experiment")

    return experiment


async def get_cache_control(skip_cache: bool = False) -> CacheControl:
    """
    Get cache control settings.

    Args:
        skip_cache (bool): Whether to skip cache

    Returns:
        CacheControl: Cache control settings
    """
    cache_control = CacheControl(skip=skip_cache)

    if skip_cache:
        return cache_control

    if not hasattr(settings, "CACHE_ENABLED") or not settings.CACHE_ENABLED:
        return cache_control

    if not REDIS_AVAILABLE:
        return cache_control

    try:
        redis_client = await get_redis_pool()
        if redis_client:
            # Test connection
            await redis_client.ping()
            cache_control.redis = redis_client
            cache_control.enabled = True
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")

    return cache_control


# Feature Flag permissions
async def get_feature_flag_by_key(
    key: str,
    db: Session = Depends(get_db),
) -> FeatureFlag:
    """Get a feature flag by key."""
    feature_flag = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    if not feature_flag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature flag with key {key} not found",
        )
    return feature_flag


async def get_feature_flag_access(
    feature_flag: FeatureFlag = Depends(get_feature_flag_by_key),
    current_user: User = Depends(get_current_user),
) -> FeatureFlag:
    """Check if user has access to the feature flag."""
    if current_user.is_superuser:
        return feature_flag

    # Check if user has permission to read feature flags
    if not check_permission(current_user, ResourceType.FEATURE_FLAG, Action.READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.FEATURE_FLAG, Action.READ),
        )

    # Check ownership for non-admin users for modification actions
    if not check_permission(current_user, ResourceType.FEATURE_FLAG, Action.UPDATE) and not check_ownership(current_user, feature_flag):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this feature flag",
        )

    return feature_flag


async def can_create_feature_flag(
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can create a feature flag."""
    if not check_permission(current_user, ResourceType.FEATURE_FLAG, Action.CREATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.FEATURE_FLAG, Action.CREATE),
        )
    return True


async def can_update_feature_flag(
    feature_flag: FeatureFlag = Depends(get_feature_flag_access),
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can update a feature flag."""
    if not check_permission(current_user, ResourceType.FEATURE_FLAG, Action.UPDATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.FEATURE_FLAG, Action.UPDATE),
        )
    return True


async def can_delete_feature_flag(
    feature_flag: FeatureFlag = Depends(get_feature_flag_access),
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can delete a feature flag."""
    if not check_permission(current_user, ResourceType.FEATURE_FLAG, Action.DELETE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.FEATURE_FLAG, Action.DELETE),
        )
    return True


# Report permissions
async def get_report_by_id(
    report_id: int,
    db: Session = Depends(get_db),
) -> Report:
    """Get a report by ID."""
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with id {report_id} not found",
        )
    return report


async def get_report_access(
    report: Report = Depends(get_report_by_id),
    current_user: User = Depends(get_current_user),
) -> Report:
    """Check if user has access to the report."""
    if current_user.is_superuser:
        return report

    # Check if user has permission to read reports
    if not check_permission(current_user, ResourceType.REPORT, Action.READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.REPORT, Action.READ),
        )

    # Check ownership for non-admin users for modification actions
    if not check_permission(current_user, ResourceType.REPORT, Action.UPDATE) and not check_ownership(current_user, report):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this report",
        )

    return report


async def can_create_report(
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can create a report."""
    if not check_permission(current_user, ResourceType.REPORT, Action.CREATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.REPORT, Action.CREATE),
        )
    return True


async def can_update_report(
    report: Report = Depends(get_report_access),
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can update a report."""
    if not check_permission(current_user, ResourceType.REPORT, Action.UPDATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.REPORT, Action.UPDATE),
        )
    return True


async def can_delete_report(
    report: Report = Depends(get_report_access),
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can delete a report."""
    if not check_permission(current_user, ResourceType.REPORT, Action.DELETE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.REPORT, Action.DELETE),
        )
    return True


def can_create_experiment(
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can create an experiment."""
    if not check_permission(current_user, ResourceType.EXPERIMENT, Action.CREATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.EXPERIMENT, Action.CREATE),
        )
    return True


def can_update_experiment(
    experiment: Experiment = Depends(get_experiment_by_key),
    current_user: User = Depends(get_current_user),
) -> bool:
    """Check if user can update an experiment."""
    # First gate the request through the standard read/ownership check
    get_experiment_access(experiment, current_user)
    if not check_permission(current_user, ResourceType.EXPERIMENT, Action.UPDATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.EXPERIMENT, Action.UPDATE),
        )
    return True


def can_delete_experiment(
    experiment: Experiment = Depends(get_experiment_by_key),
    current_user: User = Depends(get_current_user),
) -> bool:
    """
    Check if user can delete an experiment.

    WARNING: Do not use this dependency in the delete_experiment endpoint!
    There is a design conflict where this dependency chain requires ACTIVE experiments
    (via get_experiment_by_key) but the delete_experiment endpoint requires
    experiments to be in DRAFT status. Use inline permission checks in the
    delete_experiment endpoint instead.
    """
    # Gate through the standard read/ownership check first
    get_experiment_access(experiment, current_user)
    # Check if user has permission to delete experiments
    if not check_permission(current_user, ResourceType.EXPERIMENT, Action.DELETE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.EXPERIMENT, Action.DELETE),
        )

    # If not a superuser, check ownership
    if not current_user.is_superuser:
        # For Dict objects, check owner_id field
        if isinstance(experiment, dict) and str(experiment.get("owner_id")) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be the owner to delete this experiment",
            )
        # For Experiment objects, check owner_id attribute
        elif hasattr(experiment, "owner_id") and str(experiment.owner_id) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be the owner to delete this experiment",
            )

    return True


# Create a dedicated function for getting experiments for deletion
def get_experiment_for_deletion(
    experiment_key: str = Query(..., description="Key or ID of the experiment to delete"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    cache_control: Dict[str, Any] = Depends(get_cache_control),
) -> Experiment:
    """
    Get experiment by key or ID specifically for deletion purposes.
    This function accepts DRAFT experiments and raises exceptions for other statuses.

    Args:
        experiment_key: The key or ID of the experiment
        db: Database session
        current_user: Current active user
        cache_control: Cache control configuration

    Returns:
        Experiment: The experiment if it exists and is in DRAFT status

    Raises:
        HTTPException 404: If experiment not found
        HTTPException 400: If experiment not in DRAFT status
    """
    # Try to get experiment by ID first
    try:
        experiment_id = UUID(experiment_key)
        experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    except (ValueError, TypeError):
        # If not valid UUID, try by key
        experiment = db.query(Experiment).filter(Experiment.key == experiment_key).first()

    if not experiment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found"
        )

    # Check if experiment is in DRAFT status
    if experiment.status != ExperimentStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Experiment not in DRAFT status"
        )

    return experiment

async def can_delete_draft_experiment(
    current_user: User = Depends(get_current_active_user),
    experiment: Experiment = Depends(get_experiment_for_deletion),
) -> bool:
    """
    Check if user can delete a draft experiment.
    User must be either the owner of the experiment or a superuser.

    Args:
        current_user: Current active user
        experiment: Experiment to check

    Returns:
        bool: True if user can delete the experiment

    Raises:
        HTTPException 403: If user doesn't have permission to delete this experiment
    """
    # Superusers can always delete
    if current_user.is_superuser:
        return True

    # Non-superusers can only delete if they own the experiment
    if experiment.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions to delete this experiment"
        )

    return True
