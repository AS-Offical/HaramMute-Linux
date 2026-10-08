import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables where available."""

    # Local mode: run yt-dlp and audio separation locally instead of via Modal
    local_mode: bool = Field(
        default=True,
        description="Run processing locally instead of via Modal. Set to True for desktop app."
    )
    dev_mode: bool = Field(
        default=False,
        description=(
            "DEV MODE: Bypasses authentication entirely. When enabled:\n"
            "  - All API requests are allowed without X-API-Key header\n"
            "  - Returns fake user {'email': 'dev@local', 'bypass': True}\n"
            "  - Allows API key generation without Polar subscription\n"
            "  Set via MUSIC_REMOVER_DEV_MODE=true environment variable.\n"
            "  WARNING: Never enable in production!"
        )
    )

    # Polar.sh subscription settings
    polar_api_key: str | None = Field(
        default=None,
        description="Polar.sh Organization Access Token for subscription verification"
    )
    polar_org_id: str | None = Field(
        default=None,
        description="Polar.sh Organization ID"
    )
    polar_product_id_monthly: str | None = Field(
        default=None,
        description="Polar.sh Product ID for monthly subscription"
    )
    polar_product_id_yearly: str | None = Field(
        default=None,
        description="Polar.sh Product ID for yearly subscription"
    )
    polar_webhook_secret: str | None = Field(
        default=None,
        description="Polar.sh webhook secret for signature validation"
    )
    browser_for_cookies: str | None = Field(
        default=None,
        description="Browser to extract cookies from (chrome, firefox, edge, brave). Auto-detected if not set."
    )
    skip_browser_cookies: bool = Field(
        default=False,
        description="Skip browser cookie extraction entirely. Avoids macOS keychain prompts but may fail on some videos."
    )

    data_dir: Path = Field(
        default_factory=lambda: Path(
            os.getenv("MUSIC_REMOVER_DATA_DIR")
            or os.getenv("HARAMMUTE_DATA_DIR")
            or "server_data"
        ).expanduser()
    )
    max_workers: int = 5
    packaging_workers: int = Field(
        default_factory=lambda: max(1, min(2, (os.cpu_count() or 2))),
        description="Max parallel FFmpeg encodes during packaging. Each uses multiple threads, so fewer workers avoids CPU oversubscription.",
    )
    keep_hours: int = 24
    yt_dlp_binary: str = Field(default="yt-dlp")
    force_cpu: bool = Field(
        default=False,
        description="Force CPU-only processing (disable GPU). Useful for dev testing CPU fallback."
    )
    deno_binary: str = Field(default="deno")
    ffmpeg_binary: str = Field(default="ffmpeg")
    encoding_quality: int = Field(
        default=4,
        description="MP3 VBR quality (0=best/slowest, 9=worst/fastest). Default 4 balances quality and speed.",
    )
    cookies_file: Path | None = Field(default=None, description="Optional path to yt-dlp cookies file")
    download_delay: float = Field(
        default=5.0,
        description="Minimum seconds between yt-dlp media download attempts"
    )
    modal_app_name: str = "music-remover-chunked"

    model_config = {"env_prefix": "MUSIC_REMOVER_"}


settings = Settings()

# Force CPU mode must be set BEFORE any PyTorch/CUDA imports
# This hides GPU devices from CUDA runtime
if settings.force_cpu:
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

settings.data_dir.mkdir(parents=True, exist_ok=True)
if settings.cookies_file and not settings.cookies_file.exists():
    raise FileNotFoundError(f"Configured cookies file {settings.cookies_file} does not exist")
settings.data_dir.joinpath("jobs").mkdir(parents=True, exist_ok=True)
