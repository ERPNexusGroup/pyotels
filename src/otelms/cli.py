"""
CLI principal con Typer - Comandos para API, Scraper, Sync, Worker.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from otelms.config.settings import settings
from otelms.utils.logging import setup_logging, get_logger

app = typer.Typer(
    name="otelms",
    help="OtelMS API - Unofficial API for OtelMS scraping and data access",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
logger = get_logger(__name__)


def setup_app() -> None:
    """Configuración común para todos los comandos."""
    setup_logging()


# ============================================================
# COMANDO: API Server
# ============================================================
@app.command(name="api")
def run_api(
    host: str = typer.Option(settings.app_host, "--host", "-h", help="Host to bind"),
    port: int = typer.Option(settings.app_port, "--port", "-p", help="Port to bind"),
    workers: int = typer.Option(settings.app_workers, "--workers", "-w", help="Number of workers"),
    reload: bool = typer.Option(settings.app_debug, "--reload", "-r", help="Auto-reload on changes"),
) -> None:
    """Inicia el servidor FastAPI (Uvicorn)."""
    import uvicorn
    import asyncio

    # Set Windows Proactor event loop policy for subprocess support (Camoufox/Playwright)
    if hasattr(asyncio, 'WindowsProactorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    setup_app()
    logger.info("Starting API server", host=host, port=port, workers=workers, reload=reload)

    uvicorn.run(
        "otelms.api.main:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


# ============================================================
# COMANDO: Scraper
# ============================================================
@app.command(name="scraper")
def run_scraper(
    hotel_id: Optional[str] = typer.Option(
        None, "--hotel-id", help="Hotel ID to scrape (optional, uses default from .env or --all-hotels)"
    ),
    all_hotels: bool = typer.Option(
        False, "--all-hotels", help="Scrape all active hotels from database"
    ),
    username: str = typer.Option(
        settings.otelms_default_username, "--username", "-u", help="Username"
    ),
    password: str = typer.Option(
        settings.otelms_default_password, "--password", "-p", help="Password"
    ),
    target_date: Optional[str] = typer.Option(
        None, "--date", "-d", help="Target date (YYYY-MM-DD)"
    ),
    strategy: str = typer.Option(
        "calendar", "--strategy", "-s", help="Strategy: calendar, categories, detail"
    ),
    headless: bool = typer.Option(
        settings.scraper_headless, "--headless/--no-headless", help="Run browser headless"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file (JSON)"
    ),
) -> None:
    """Ejecuta scraping directo de OtelMS."""
    from otelms.scraping.orchestrator import ScrapingOrchestrator
    from otelms.services.sync_service import SyncService

    setup_app()

    async def _run() -> None:
        if all_hotels:
            console.print("[blue]Scraping all active hotels from database...[/blue]")
            from otelms.domain.repositories.database import get_db_session
            from otelms.domain.repositories import HotelRepository

            async with get_db_session() as session:
                hotel_repo = HotelRepository(session)
                hotels = await hotel_repo.get_active_with_config()

            for hotel in hotels:
                console.print(f"[blue]Scraping hotel: {hotel.id} ({hotel.name})[/blue]")
                svc = await SyncService.from_hotel(hotel)
                await svc.initialize()

                try:
                    if strategy == "calendar":
                        result = await svc._orchestrator.scrape_calendar(target_date)
                    elif strategy == "categories":
                        result = await svc._orchestrator.scrape_categories(target_date)
                    elif strategy == "detail":
                        if not target_date:
                            console.print("[red]Error: --date requerido para strategy=detail[/red]")
                            raise typer.Exit(1)
                        result = await svc._orchestrator.scrape_reservation_details(target_date)
                    else:
                        console.print(f"[red]Strategy desconocida: {strategy}[/red]")
                        raise typer.Exit(1)

                    console.print(f"[green]✓ Hotel {hotel.id} completado: {result.operation}[/green]")
                finally:
                    await svc.close()
        else:
            # Single hotel mode - use provided or default hotel_id
            target_hotel_id = hotel_id or settings.otelms_default_hotel_id
            orchestrator = ScrapingOrchestrator(
                hotel_id=target_hotel_id,
                username=username,
                password=password,
                headless=headless,
            )

            try:
                await orchestrator.initialize()

                if strategy == "calendar":
                    result = await orchestrator.scrape_calendar(target_date)
                elif strategy == "categories":
                    result = await orchestrator.scrape_categories(target_date)
                elif strategy == "detail":
                    if not target_date:
                        console.print("[red]Error: --date requerido para strategy=detail[/red]")
                        raise typer.Exit(1)
                    result = await orchestrator.scrape_reservation_details(target_date)
                else:
                    console.print(f"[red]Strategy desconocida: {strategy}[/red]")
                    raise typer.Exit(1)

                console.print(f"[green]✓ Scraping completado: {len(result)} items[/green]")

                if output:
                    import json
                    with open(output, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
                    console.print(f"[green]✓ Guardado en {output}[/green]")
                else:
                    console.print_json(data=result[:5] if isinstance(result, list) else result)

            finally:
                await orchestrator.close()

        asyncio.run(_run())


# ============================================================
# COMANDO: Sync (Sincronización completa)
# ============================================================
@app.command(name="sync")
def run_sync(
    hotel_id: str = typer.Option(
        settings.otelms_default_hotel_id, "--hotel-id", help="Hotel ID to sync"
    ),
    username: str = typer.Option(
        settings.otelms_default_username, "--username", "-u", help="Username"
    ),
    password: str = typer.Option(
        settings.otelms_default_password, "--password", "-p", help="Password"
    ),
    full: bool = typer.Option(False, "--full", "-f", help="Full sync (calendar + categories + details)"),
    calendar_only: bool = typer.Option(False, "--calendar", help="Only calendar sync"),
    categories_only: bool = typer.Option(False, "--categories", help="Only categories sync"),
    details_only: bool = typer.Option(False, "--details", help="Only reservation details sync"),
) -> None:
    """Ejecuta sincronización completa con base de datos."""
    from otelms.services.sync_service import SyncService

    setup_app()

    async def _run() -> None:
        sync_service = SyncService(
            hotel_id=hotel_id,
            username=username,
            password=password,
        )

        try:
            await sync_service.initialize()

            if full or (not calendar_only and not categories_only and not details_only):
                console.print("[blue]Iniciando sincronización completa...[/blue]")
                result = await sync_service.full_sync()
            elif calendar_only:
                console.print("[blue]Sincronizando calendario...[/blue]")
                result = await sync_service.sync_calendar()
            elif categories_only:
                console.print("[blue]Sincronizando categorías...[/blue]")
                result = await sync_service.sync_categories()
            elif details_only:
                console.print("[blue]Sincronizando detalles de reservas...[/blue]")
                result = await sync_service.sync_reservation_details()
            else:
                console.print("[red]Opción no válida[/red]")
                raise typer.Exit(1)

            # Mostrar resultados
            table = Table(title="Resultados de Sincronización")
            table.add_column("Métrica", style="cyan")
            table.add_column("Valor", style="green")
            for key, value in result.items():
                table.add_row(key.replace("_", " ").title(), str(value))
            console.print(table)

        finally:
            await sync_service.close()

    asyncio.run(_run())


# ============================================================
# COMANDO: Database
# ============================================================
db_app = typer.Typer(name="db", help="Database management commands")
app.add_typer(db_app)


@db_app.command(name="init")
def db_init() -> None:
    """Inicializa la base de datos (crea tablas)."""
    from otelms.domain.repositories.database import init_db

    setup_app()
    console.print("[blue]Inicializando base de datos...[/blue]")
    asyncio.run(init_db())
    console.print("[green]✓ Base de datos inicializada[/green]")


@db_app.command(name="drop")
def db_drop(confirm: bool = typer.Option(False, "--yes", "-y", help="Confirm drop")) -> None:
    """Elimina todas las tablas (¡CUIDADO!)."""
    from otelms.domain.repositories.database import db

    if not confirm:
        console.print("[red]Use --yes para confirmar[/red]")
        raise typer.Exit(1)

    setup_app()
    console.print("[yellow]Eliminando todas las tablas...[/yellow]")
    asyncio.run(db.drop_all())
    console.print("[green]✓ Tablas eliminadas[/green]")


@db_app.command(name="migrate")
def db_migrate(message: str = typer.Option("", "--message", "-m", help="Migration message")) -> None:
    """Genera y ejecuta migraciones con Alembic."""
    import subprocess

    setup_app()
    console.print("[blue]Generando migración...[/blue]")
    cmd = ["alembic", "revision", "--autogenerate"]
    if message:
        cmd.extend(["-m", message])
    subprocess.run(cmd, check=True)

    console.print("[blue]Ejecutando migración...[/blue]")
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    console.print("[green]✓ Migración completada[/green]")


@db_app.command(name="seed")
def db_seed(
    hotel_id: str = typer.Option(settings.otelms_default_hotel_id, "--hotel-id"),
    username: str = typer.Option(settings.otelms_default_username, "--username"),
    password: str = typer.Option(settings.otelms_default_password, "--password"),
) -> None:
    """Pobla la BD con datos iniciales (hotel, api key)."""
    from otelms.domain.repositories.database import db
    from otelms.domain.entities import Hotel, ApiKey
    from otelms.config.settings import settings
    import hashlib
    import secrets

    setup_app()

    async def _run() -> None:
        async with db.session() as session:
            # Crear hotel si no existe
            hotel = await session.get(Hotel, hotel_id)
            if not hotel:
                pwd_hash = hashlib.sha256(password.encode()).hexdigest()
                hotel = Hotel(
                    id=hotel_id,
                    name="Harmony Hotel Group",
                    domain=settings.otelms_base_domain,
                    username=username,
                    password_hash=pwd_hash,
                    is_active=True,
                )
                session.add(hotel)
                console.print(f"[green]✓ Hotel creado: {hotel_id}[/green]")
            else:
                console.print(f"[yellow]Hotel ya existe: {hotel_id}[/yellow]")

            # Crear API key por defecto
            api_key_value = settings.api_key
            key_hash = hashlib.sha256(api_key_value.encode()).hexdigest()
            api_key = await session.get(ApiKey, "default")
            if not api_key:
                api_key = ApiKey(
                    id="default",
                    name="Default API Key",
                    key_hash=key_hash,
                    is_active=True,
                    rate_limit=60,
                )
                session.add(api_key)
                console.print("[green]✓ API Key creada[/green]")
            else:
                console.print("[yellow]API Key ya existe[/yellow]")

            await session.commit()

    asyncio.run(_run())
    console.print("[green]✓ Seed completado[/green]")


# ============================================================
# COMANDO: Worker (Celery)
# ============================================================
@app.command(name="worker")
def run_worker(
    concurrency: int = typer.Option(2, "--concurrency", "-c", help="Worker concurrency"),
    loglevel: str = typer.Option("INFO", "--loglevel", "-l", help="Log level"),
) -> None:
    """Inicia worker de Celery para tareas en background."""
    import subprocess

    setup_app()
    logger.info("Starting Celery worker", concurrency=concurrency, loglevel=loglevel)

    cmd = [
        "celery",
        "-A", "otelms.tasks.celery_app",
        "worker",
        f"--concurrency={concurrency}",
        f"--loglevel={loglevel}",
    ]
    subprocess.run(cmd)


# ============================================================
# COMANDO: Beat (Scheduler)
# ============================================================
@app.command(name="beat")
def run_beat(
    loglevel: str = typer.Option("INFO", "--loglevel", "-l", help="Log level"),
) -> None:
    """Inicia Celery Beat (scheduler periódico)."""
    import subprocess

    setup_app()
    logger.info("Starting Celery Beat", loglevel=loglevel)

    cmd = [
        "celery",
        "-A", "otelms.tasks.celery_app",
        "beat",
        f"--loglevel={loglevel}",
        "--scheduler", "celery.beat.PersistentScheduler",
    ]
    subprocess.run(cmd)


# ============================================================
# COMANDO: Shell / REPL
# ============================================================
@app.command(name="shell")
def run_shell() -> None:
    """Abre shell interactivo con contexto de la app."""
    import IPython

    setup_app()
    from otelms.domain.repositories.database import get_db_session
    from otelms.domain.entities import Hotel, Reservation, Guest, Category, Room
    from otelms.services.sync_service import SyncService

    console.print("[bold blue]OtelMS API Shell[/bold blue]")
    console.print("Objetos disponibles: db_session, Hotel, Reservation, Guest, Category, Room, SyncService")

    async def get_session():
        async with get_db_session() as s:
            return s

    # No se puede usar await en shell síncrono, pasar función
    IPython.embed(
        user_ns={
            "get_db_session": get_session,
            "Hotel": Hotel,
            "Reservation": Reservation,
            "Guest": Guest,
            "Category": Category,
            "Room": Room,
            "SyncService": SyncService,
            "settings": settings,
        }
    )


# ============================================================
# COMANDO: Version
# ============================================================
@app.command(name="version")
def version() -> None:
    """Muestra versión de la aplicación."""
    from otelms import __version__

    console.print(f"OtelMS API v{__version__}")


if __name__ == "__main__":
    app()