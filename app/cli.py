import typer
from app.db import init_db as db_init
from app.services.provider_discovery import crawl_enabled_sources, normalize_and_deduplicate
from app.orchestrator import run_update_all, RunSummary

app = typer.Typer(help="CLI tool for BestAIPrice parser")


@app.command("init-db")
def init_db_cmd():
    """Initialize SQLite database tables."""
    db_init()
    typer.echo("Database initialized successfully.")


@app.command("crawl-sources")
def crawl_sources_cmd():
    """Discover providers from enabled catalog sources and deduplicate in DB."""
    db_init()
    discovered = crawl_enabled_sources()
    providers = normalize_and_deduplicate(discovered)
    typer.echo(f"Crawled {len(discovered)} raw entries from sources.")
    typer.echo(f"Saved {len(providers)} unique providers to database.")


@app.command("update-all")
def update_all_cmd():
    """Run full parser pipeline end-to-end and publish output JSON."""
    summary: RunSummary = run_update_all()

    typer.echo("\n=================== RUN SUMMARY ===================")
    typer.echo(f"sources_processed       : {summary.sources_processed}")
    typer.echo(f"providers_found         : {summary.providers_found}")
    typer.echo(f"providers_unique        : {summary.providers_unique}")
    typer.echo(f"pricing_pages_found     : {summary.pricing_pages_found}")
    typer.echo(f"prices_extracted        : {summary.prices_extracted}")
    typer.echo(f"prices_published        : {summary.prices_published}")
    typer.echo(f"models_published        : {summary.models_published}")
    typer.echo(f"records_needing_review  : {summary.records_needing_review}")
    typer.echo(f"errors_count            : {summary.errors_count}")
    typer.echo(f"duration_seconds        : {summary.duration_seconds}s")
    typer.echo("===================================================\n")

    if summary.hard_failure:
        typer.echo("Pipeline completed with critical errors.", err=True)
        raise typer.Exit(code=1)
    else:
        typer.echo("Pipeline completed successfully.")


if __name__ == "__main__":
    app()
