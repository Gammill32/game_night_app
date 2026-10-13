"""Maintenance commands: `flask badges recheck [--dry-run]`."""

import click
from flask.cli import AppGroup

badges_cli = AppGroup("badges", help="Badge maintenance.")


@badges_cli.command("recheck")
@click.option("--dry-run", is_flag=True, help="Show what would change without saving.")
def recheck(dry_run):
    """Re-judge every finalized night with the current badge rules.

    Adds badges people earned but don't have, removes ones that no longer
    qualify, and leaves the rest untouched. All changes are saved together.
    """
    from app.extensions import db
    from app.services.badge_services import recheck_badges

    try:
        changes = recheck_badges(apply=not dry_run)
    except Exception:
        db.session.rollback()
        raise

    if not changes:
        click.echo("Every badge already matches the rules; nothing to change.")
        return
    added = removed = 0
    for change in changes:
        click.echo(change["badge"])
        for name, night_date in change["added"]:
            click.echo(f"  + {name} ({night_date.isoformat()})")
        for name in change["removed"]:
            click.echo(f"  - {name}")
        added += len(change["added"])
        removed += len(change["removed"])
    summary = f"{added} to add, {removed} to remove."
    if dry_run:
        click.echo(f"Dry run: {summary} Nothing was saved.")
    else:
        click.echo(f"Saved: {summary}")
