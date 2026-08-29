"""Command-line entry point for FormHarvester."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from pydantic import ValidationError

from formharvester.cli.app import Bot
from formharvester.core import __VERSION__
from formharvester.leads import LeadRepository
from formharvester.settings import (
    CampaignProfile,
    Settings,
    config_home,
    data_dir,
    list_profiles,
    load_profile,
    load_settings,
    save_profile,
    save_settings,
)

__all__ = ["Bot", "cli", "main"]

cli = typer.Typer(
    help="FormHarvester: search the web, scrape contacts and submit forms.",
    no_args_is_help=True,
    add_completion=False,
)


def _load(profile_name: str | None) -> tuple[Settings, CampaignProfile]:
    """Load settings and the requested profile."""
    settings = load_settings()
    name = profile_name or settings.active_profile
    return settings, load_profile(name)


@cli.command()
def run(
    profile: Annotated[str | None, typer.Option("--profile", "-p", help="Campaign profile to run.")] = None,
    headless: Annotated[bool | None, typer.Option(help="Hide the browser window.")] = None,
    send_form: Annotated[bool | None, typer.Option(help="Submit contact forms once filled.")] = None,
    skip_ads: Annotated[bool | None, typer.Option(help="Skip ad results.")] = None,
    max_time: Annotated[int | None, typer.Option(help="Seconds allowed per site.")] = None,
    max_pages: Annotated[int | None, typer.Option(help="Result pages to walk per query.")] = None,
    start_page: Annotated[int | None, typer.Option(help="Results page to start from.")] = None,
) -> None:
    """Run the harvest loop, resuming any unfinished progress."""
    settings, campaign = _load(profile)

    # Flags override the saved settings for this run only.
    overrides = {
        "headless": headless,
        "send_form": send_form,
        "skip_ads": skip_ads,
        "max_time": max_time,
    }
    engine = settings.engine.model_copy(update={k: v for k, v in overrides.items() if v is not None})
    google_overrides = {"max_pages": max_pages, "start_page": start_page}
    google = settings.google.model_copy(update={k: v for k, v in google_overrides.items() if v is not None})
    settings = settings.model_copy(update={"engine": engine, "google": google})

    if not campaign.queries:
        typer.echo(f"Profile '{campaign.name}' has no queries. Add some in the GUI ('formharvester gui').")
        raise typer.Exit(code=1)

    bot = Bot(settings, campaign)
    try:
        remaining_google = [i[0] for i in bot.get_no_progress(is_google=True)]
        remaining_urls = [i[0] for i in bot.get_no_progress()]
        if remaining_urls or remaining_google:
            bot.resume(remaining_urls, remaining_google)
        else:
            bot.run()
    finally:
        bot.close()


@cli.command()
def discover(
    query: Annotated[list[str], typer.Argument(help="Search terms. Repeat for several.")],
    max_pages: Annotated[int | None, typer.Option(help="Result pages to walk per query.")] = None,
    start_page: Annotated[int | None, typer.Option(help="Results page to start from.")] = None,
    headless: Annotated[bool | None, typer.Option(help="Hide the browser window.")] = None,
    keyword: Annotated[
        list[str] | None,
        typer.Option("--keyword", "-k", help="Only keep URLs containing this. Repeat to allow several."),
    ] = None,
) -> None:
    """Search the web and print the site URLs found, one per line.

    Read-only: nothing is submitted, and no progress or ledger files are
    touched. Pipe it into a file to build a target list.
    """
    from formharvester.api import CaptchaError, FormFillDetails, FormHarvester, HarvesterOptions

    settings = load_settings()
    google = settings.google

    options = HarvesterOptions(
        send_form=False,
        headless=settings.engine.headless if headless is None else headless,
        skip_ads=settings.engine.skip_ads,
        start_page=start_page if start_page is not None else google.start_page,
        max_pages=max_pages if max_pages is not None else google.max_pages,
        min_delay=google.min_delay,
        max_delay=google.max_delay,
        search_timer=google.search_timer,
        captcha_sleep=google.captcha_sleep,
        keywords=list(keyword or []),
        captcha_provider=settings.captcha.provider or None,
        dbc_username=settings.captcha.dbc_username or None,
        dbc_password=settings.captcha.dbc_password or None,
        twocaptcha_api_key=settings.captcha.twocaptcha_api_key or None,
    )

    try:
        with FormHarvester(FormFillDetails(), options) as harvester:
            for url in harvester.discover_many(query):
                typer.echo(url)
    except CaptchaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


@cli.command()
def gui() -> None:
    """Open the desktop interface."""
    from formharvester.gui import launch

    launch()


settings_app = typer.Typer(help="Inspect and change saved settings.", no_args_is_help=True)
profile_app = typer.Typer(help="Manage campaign profiles.", no_args_is_help=True)
leads_app = typer.Typer(help="Inspect and export local lead intelligence.", no_args_is_help=True)
cli.add_typer(settings_app, name="settings")
cli.add_typer(profile_app, name="profile")
cli.add_typer(leads_app, name="leads")


@settings_app.command("show")
def settings_show() -> None:
    """Print the current settings as JSON."""
    typer.echo(load_settings().model_dump_json(indent=2))


@settings_app.command("path")
def settings_path() -> None:
    """Print where settings and profiles are stored."""
    typer.echo(str(config_home()))


@settings_app.command("set")
def settings_set(
    key: Annotated[str, typer.Argument(help="Dotted key, e.g. engine.headless or google.max_pages.")],
    value: Annotated[str, typer.Argument(help="New value.")],
) -> None:
    """Set one setting, e.g. 'formharvester settings set engine.headless true'."""
    settings = load_settings()
    section, _, field = key.partition(".")
    if not field or not hasattr(settings, section):
        typer.echo(f"Unknown key '{key}'. Use one of: engine.*, google.*, captcha.*, llm.*")
        raise typer.Exit(code=1)

    if not hasattr(getattr(settings, section), field):
        typer.echo(f"Unknown key '{key}'.")
        raise typer.Exit(code=1)

    # Re-validate the whole dict so pydantic coerces the string into the
    # field's real type; model_copy would skip validation and store the string.
    data = settings.model_dump()
    data[section][field] = value
    try:
        updated = Settings.model_validate(data)
    except ValidationError as exc:
        typer.echo(f"Invalid value for {key}: {exc.errors()[0]['msg']}")
        raise typer.Exit(code=1) from None

    save_settings(updated)
    typer.echo(f"{key} = {getattr(getattr(updated, section), field)}")


@profile_app.command("list")
def profile_list() -> None:
    """List saved campaign profiles."""
    active = load_settings().active_profile
    names = list_profiles()
    if not names:
        typer.echo("No profiles yet.")
        return
    for name in names:
        typer.echo(f"{'*' if name == active else ' '} {name}")


@profile_app.command("show")
def profile_show(name: Annotated[str | None, typer.Argument()] = None) -> None:
    """Print a campaign profile as JSON."""
    settings = load_settings()
    typer.echo(load_profile(name or settings.active_profile).model_dump_json(indent=2))


@profile_app.command("create")
def profile_create(name: Annotated[str, typer.Argument(help="Profile name.")]) -> None:
    """Create an empty campaign profile."""
    path = save_profile(CampaignProfile(name=name))
    typer.echo(f"Created {path}")


@profile_app.command("use")
def profile_use(name: Annotated[str, typer.Argument(help="Profile to make active.")]) -> None:
    """Set the profile used when --profile is omitted."""
    if name not in list_profiles():
        typer.echo(f"No profile named '{name}'.")
        raise typer.Exit(code=1)
    settings = load_settings()
    save_settings(settings.model_copy(update={"active_profile": name}))
    typer.echo(f"Active profile: {name}")


@leads_app.command("list")
def leads_list(
    status: Annotated[str | None, typer.Option(help="Filter by lead status.")] = None,
    campaign: Annotated[str | None, typer.Option("--campaign", "-c", help="Campaign to inspect.")] = None,
) -> None:
    """Print local lead records as one JSON object per line."""
    selected = campaign or load_settings().active_profile
    with LeadRepository(data_dir()) as leads:
        records = leads.list_leads(campaign=selected, status=status, limit=1000)
    for record in records:
        typer.echo(json.dumps(record.to_dict(), ensure_ascii=False))


@leads_app.command("metrics")
def leads_metrics(
    campaign: Annotated[str | None, typer.Option("--campaign", "-c", help="Campaign to inspect.")] = None,
) -> None:
    """Print the local lead funnel metrics as JSON."""
    selected = campaign or load_settings().active_profile
    with LeadRepository(data_dir()) as leads:
        typer.echo(json.dumps(leads.metrics(selected)))


@leads_app.command("export")
def leads_export(
    destination: Annotated[str | None, typer.Option("--output", "-o", help="CSV output path.")] = None,
    campaign: Annotated[str | None, typer.Option("--campaign", "-c", help="Campaign to export.")] = None,
) -> None:
    """Export local lead records to CSV."""
    selected = campaign or load_settings().active_profile
    path = destination or str(data_dir() / f"{selected}_leads.csv")
    with LeadRepository(data_dir()) as leads:
        exported = leads.export_csv(path, campaign=selected)
    typer.echo(str(exported))


@cli.command()
def version() -> None:
    """Print the FormHarvester version."""
    typer.echo(__VERSION__)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
