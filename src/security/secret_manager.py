"""
Google Secret Manager Integration
Load secrets from GCP Secret Manager with env var fallback
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from google.cloud import secretmanager
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False
    logger.info("google-cloud-secret-manager not installed, using env vars only")


class SecretManager:
    """
    Loads secrets with fallback chain:
    1. Environment variables (highest priority - for local dev)
    2. Google Secret Manager (production)
    3. Default value (if provided)
    """

    def __init__(self, project_id: str = ""):
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID", "")
        self._client = None
        self._cache: dict = {}

        if GCP_AVAILABLE and self.project_id:
            try:
                self._client = secretmanager.SecretManagerServiceClient()
                logger.info(f"Secret Manager initialized (project: {self.project_id})")
            except Exception as e:
                logger.warning(f"Secret Manager init failed: {e}")

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a secret value."""
        # 1. Environment variable
        env_val = os.environ.get(key)
        if env_val:
            return env_val

        # 2. Cache
        if key in self._cache:
            return self._cache[key]

        # 3. GCP Secret Manager
        if self._client and self.project_id:
            try:
                name = f"projects/{self.project_id}/secrets/{key}/versions/latest"
                response = self._client.access_secret_version(request={"name": name})
                value = response.payload.data.decode("utf-8")
                self._cache[key] = value
                logger.info(f"Loaded secret from GCP: {key}")
                return value
            except Exception as e:
                logger.debug(f"Secret {key} not found in GCP: {e}")

        return default

    def require(self, key: str) -> str:
        """Get a secret, raise if not found."""
        value = self.get(key)
        if value is None:
            raise RuntimeError(
                f"Required secret '{key}' not found. "
                f"Set it as env var or in GCP Secret Manager."
            )
        return value


# Singleton
secrets = SecretManager()
