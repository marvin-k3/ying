"""FastAPI application for RTSP Music Tagger."""

import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Config
from .db.migrate import MigrationManager
from .logging_setup import setup_logging
from .metrics import get_metrics, get_metrics_openmetrics
from .middleware import MetricsMiddleware
from .tracing import setup_tracing
from .web.routes import router
from .worker import WorkerManager


# Global worker manager for shutdown handling
worker_manager: WorkerManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    global worker_manager
    
    # Load configuration
    config = Config()
    
    # Setup logging and tracing
    setup_logging(
        level=config.log_level,
        structured=config.structured_logs,
    )
    
    setup_tracing(
        service_name=config.otel_service_name,
        endpoint=config.otel_exporter_otlp_endpoint,
        sample_rate=config.otel_traces_sampler_arg,
    )
    
    # Run migrations
    migration_manager = MigrationManager(config.db_path)
    await migration_manager.migrate_all()
    
    # Start worker manager
    worker_manager = WorkerManager(config)
    await worker_manager.start_all()
    
    # Store config in app state
    app.state.config = config
    app.state.worker_manager = worker_manager
    
    yield
    
    # Shutdown workers
    if worker_manager:
        await worker_manager.stop_all()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="RTSP Music Tagger",
        description="Real-time music recognition from RTSP streams",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # Add middleware
    app.add_middleware(MetricsMiddleware)
    
    # Mount static files
    static_path = Path(__file__).parent / "web" / "static"
    static_path.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
    
    # Setup templates
    template_path = Path(__file__).parent / "web" / "templates"
    template_path.mkdir(parents=True, exist_ok=True)
    app.state.templates = Jinja2Templates(directory=str(template_path))
    
    # Include routes
    app.include_router(router)
    
    # Add basic endpoints
    @app.get("/healthz")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": "rtsp-music-tagger"}
    
    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint."""
        return get_metrics()
    
    @app.get("/metrics/openmetrics")
    async def metrics_openmetrics():
        """OpenMetrics format metrics endpoint.""" 
        return get_metrics_openmetrics()
    
    return app


# Create the app instance
app = create_app()


def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals."""
    print(f"Received signal {signum}, shutting down...")
    sys.exit(0)


def main() -> None:
    """Main entry point for the application."""
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start the application
    import uvicorn
    config = Config()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=config.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
