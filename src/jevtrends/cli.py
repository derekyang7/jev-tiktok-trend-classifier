"""Command-line interface (spec §5). Run through scripts/scan.sh so API keys are loaded."""

import typer

from jevtrends.opportunities.cli import opportunities_app
from jevtrends.ugc.cli import ugc_app

app = typer.Typer(no_args_is_help=True, help="Find TikTok trends using Jev.")
app.add_typer(opportunities_app, name="opportunities")
app.add_typer(ugc_app, name="ugc")
