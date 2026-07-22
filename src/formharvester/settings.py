"""Configuration model for FormHarvester.

``formharvester.json`` holds engine settings and ``profiles/<name>.json`` holds
a campaign (the form-fill details plus the search queries).

All three front ends - the CLI, the GUI and the library API - build these same
objects, so behaviour cannot drift between them.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "CampaignProfile",
    "CaptchaSettings",
    "EngineSettings",
    "FormFill",
    "GoogleSettings",
    "Settings",
    "config_home",
    "data_dir",
    "delete_profile",
    "list_profiles",
    "load_profile",
    "load_settings",
    "log_dir",
    "profiles_dir",
    "save_profile",
    "save_settings",
]

SETTINGS_FILE = "formharvester.json"


def config_home() -> Path:
    """Directory holding ``formharvester.json`` and ``profiles/``.

    ``FORMHARVESTER_HOME`` wins. Otherwise an existing config in the working
    directory keeps working in place (how the CLI has always behaved), and a
    fresh install falls back to the user's home so the GUI executable does not
    scatter files into whatever directory it was launched from.
    """
    env = os.environ.get("FORMHARVESTER_HOME")
    if env:
        return Path(env)

    cwd = Path.cwd()
    if (cwd / SETTINGS_FILE).exists():
        return cwd
    return Path.home() / ".formharvester"


def profiles_dir(home: Path | None = None) -> Path:
    return (home or config_home()) / "profiles"


def data_dir(home: Path | None = None) -> Path:
    """Scraped emails, progress files and the visited-site log."""
    return (home or config_home()) / "data"


def log_dir(home: Path | None = None) -> Path:
    """Per-error page dumps and screenshots."""
    return (home or config_home()) / "log"


class EngineSettings(BaseModel):
    skip_ads: bool = False
    send_form: bool = False
    headless: bool = False
    max_time: int = Field(default=30, ge=1, description="Seconds allowed per site")
    generate_email_sources: bool = True
    debug_form: bool = Field(default=False, description="Fill forms but never submit")


class GoogleSettings(BaseModel):
    start_page: int = Field(default=1, ge=1)
    max_pages: int = Field(default=3, ge=1)
    min_delay: int = Field(default=8, ge=0, description="Seconds between searches")
    max_delay: int = Field(default=25, ge=0)
    captcha_sleep: int = Field(default=60, ge=0, description="Minutes to pause after a Google captcha, 0 disables")
    search_timer: int = Field(default=20, ge=0, description="Minutes between search batches")

    @model_validator(mode="after")
    def _delays_ordered(self) -> GoogleSettings:
        if self.max_delay < self.min_delay:
            raise ValueError("max_delay must be greater than or equal to min_delay")
        return self


class CaptchaSettings(BaseModel):
    provider: str = Field(default="", description="deathbycaptcha, 2captcha or blank to auto-detect")
    dbc_username: str = ""
    dbc_password: str = ""
    twocaptcha_api_key: str = ""


class Settings(BaseModel):
    active_profile: str = "default"
    engine: EngineSettings = Field(default_factory=EngineSettings)
    google: GoogleSettings = Field(default_factory=GoogleSettings)
    captcha: CaptchaSettings = Field(default_factory=CaptchaSettings)


class FormFill(BaseModel):
    """Values used to fill contact forms."""

    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    email: str = ""
    location: str = ""
    city: str = ""
    state: str = ""
    subject: str = ""
    message: str = ""

    def as_engine_details(self) -> dict[str, str]:
        return self.model_dump()


class CampaignProfile(BaseModel):
    """One campaign: who the forms are filled as, and what to search for."""

    name: str = "default"
    form_fill: FormFill = Field(default_factory=FormFill)
    queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


# --- persistence ---------------------------------------------------------


def load_settings(home: Path | None = None) -> Settings:
    home = home or config_home()
    path = home / SETTINGS_FILE
    if not path.exists():
        return Settings()
    return Settings.model_validate_json(path.read_text(encoding="utf-8"))


def save_settings(settings: Settings, home: Path | None = None) -> Path:
    home = home or config_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / SETTINGS_FILE
    path.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    return path


def list_profiles(home: Path | None = None) -> list[str]:
    directory = profiles_dir(home)
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def load_profile(name: str, home: Path | None = None) -> CampaignProfile:
    path = profiles_dir(home) / f"{name}.json"
    if not path.exists():
        return CampaignProfile(name=name)
    return CampaignProfile.model_validate_json(path.read_text(encoding="utf-8"))


def save_profile(profile: CampaignProfile, home: Path | None = None) -> Path:
    directory = profiles_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile.name}.json"
    path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    return path


def delete_profile(name: str, home: Path | None = None) -> bool:
    path = profiles_dir(home) / f"{name}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
