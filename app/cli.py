import typer
from app.db import init_db as db_init
from app.services.provider_discovery import crawl_enabled_sources, normalize_and_deduplicate
from app.services.payment_methods import sync_payment_methods_into_frontend_json
from app.services.trust_check import sync_domain_age_into_frontend_json
from app.services.api_descriptions import build_api_descriptions
from app.services.provider_descriptions import build_provider_descriptions
from app.services.exporter import export_api_descriptions_json_atomically, export_provider_descriptions_json_atomically
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


@app.command("sync-payment-methods")
def sync_payment_methods_cmd():
    """Refresh payment_methods in public/data/providers.json from
    config/payment_methods.json without re-running the full pipeline."""
    changed = sync_payment_methods_into_frontend_json()
    typer.echo(f"Updated payment_methods for {changed} row(s) in public/data/providers.json.")


@app.command("generate-api-descriptions")
def generate_api_descriptions_cmd():
    """Render public/data/api_descriptions.json (per-vendor "cheap API" intro
    cards) from config/api_vendors.json. Independent of the crawl pipeline."""
    rows = build_api_descriptions()
    export_api_descriptions_json_atomically(rows)
    typer.echo(f"Wrote {len(rows)} vendor card(s) to public/data/api_descriptions.json.")


@app.command("sync-domain-age")
def sync_domain_age_cmd():
    """Refresh domain_created_at/domain_age_days in public/data/providers.json
    from values already stored in the database, without re-running the full
    pipeline (no new RDAP calls)."""
    changed = sync_domain_age_into_frontend_json()
    typer.echo(f"Updated domain age fields for {changed} row(s) in public/data/providers.json.")


@app.command("generate-provider-descriptions")
def generate_provider_descriptions_cmd():
    """Render public/data/provider_descriptions.json (per-reseller intro
    cards) from config/provider_descriptions.json. Independent of the crawl
    pipeline."""
    rows = build_provider_descriptions()
    export_provider_descriptions_json_atomically(rows)
    typer.echo(f"Wrote {len(rows)} provider description(s) to public/data/provider_descriptions.json.")


if __name__ == "__main__":
    app()
