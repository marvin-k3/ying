"""Web routes for the RTSP Music Tagger."""

import csv
import io
from datetime import date, datetime

import aiosqlite
import pytz
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from ..config import Config
from ..db.repo import PlayRepository, RecognitionRepository
from ..worker import WorkerManager

router = APIRouter()

# Pacific timezone for display
PACIFIC_TZ = pytz.timezone("America/Los_Angeles")


class PlayRecord(BaseModel):
    """Pydantic model for play records."""

    id: int
    track_id: int
    stream_id: int
    recognized_at_utc: datetime
    recognized_at_pt: str = Field(..., description="Pacific Time formatted string")
    dedup_bucket: int
    confidence: float | None
    title: str
    artist: str
    album: str | None
    artwork_url: str | None
    stream_name: str


class PlaysResponse(BaseModel):
    """Response model for plays API."""

    plays: list[PlayRecord]
    total_count: int
    date: str
    stream: str


class RecognitionRecord(BaseModel):
    """Pydantic model for recognition records."""

    id: int
    stream_id: int
    stream_name: str
    provider: str
    recognized_at_utc: datetime
    recognized_at_pt: str = Field(..., description="Pacific Time formatted string")
    window_start_utc: datetime | None
    window_end_utc: datetime | None
    track_id: int | None
    title: str | None
    artist: str | None
    confidence: float | None
    latency_ms: int | None
    error_message: str | None
    has_raw_response: bool = Field(
        ..., description="Whether raw JSON response is available"
    )


class RecognitionsResponse(BaseModel):
    """Response model for recognitions API."""

    recognitions: list[RecognitionRecord]
    total_count: int
    stream: str | None
    provider: str | None


def convert_utc_to_pt(utc_dt: datetime) -> str:
    """Convert UTC datetime to Pacific Time string."""
    if utc_dt.tzinfo is None:
        utc_dt = pytz.UTC.localize(utc_dt)
    pt_dt = utc_dt.astimezone(PACIFIC_TZ)
    return pt_dt.strftime("%H:%M:%S")


def get_pt_date_today() -> date:
    """Get today's date in Pacific Time."""
    pt_now = datetime.now(PACIFIC_TZ)
    return pt_now.date()


@router.get("/", response_class=HTMLResponse)
async def day_view(request: Request):
    """Day view - main page showing plays for a date."""
    config: Config = request.app.state.config
    templates = request.app.state.templates

    # Get today's date in PT as default
    today_pt = get_pt_date_today()

    # Get available streams from config
    streams = []
    for i in range(1, config.stream_count + 1):
        stream_config = getattr(config, f"stream_{i}", None)
        if stream_config and stream_config.enabled:
            streams.append(stream_config.name)

    return templates.TemplateResponse(
        request,
        "day_view.html",
        {
            "today": today_pt.isoformat(),
            "streams": streams,
        },
    )


@router.get("/api/plays", response_model=PlaysResponse)
async def get_plays(
    request: Request,
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    stream: str = Query("all", description="Stream name or 'all'"),
    format: str = Query("json", description="Response format: 'json' or 'csv'"),
):
    """Get plays for a specific date and stream."""
    config: Config = request.app.state.config

    # Parse and validate date
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        ) from e

    # Validate stream name
    stream_filter = None if stream == "all" else stream
    if stream_filter:
        # Check if stream exists in config
        valid_streams = []
        for i in range(1, config.stream_count + 1):
            stream_config = getattr(config, f"stream_{i}", None)
            if stream_config and stream_config.enabled:
                valid_streams.append(stream_config.name)

        if stream_filter not in valid_streams:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stream '{stream_filter}'. Valid streams: {valid_streams}",
            )

    # Query plays from database
    play_repo = PlayRepository(config.db_path)
    plays_data = await play_repo.get_plays_by_date(target_date, stream_filter)

    # Convert to PlayRecord models with PT time conversion
    play_records = []
    for play_data in plays_data:
        play_record = PlayRecord(
            id=play_data["id"],
            track_id=play_data["track_id"],
            stream_id=play_data["stream_id"],
            recognized_at_utc=play_data["recognized_at_utc"],
            recognized_at_pt=convert_utc_to_pt(play_data["recognized_at_utc"]),
            dedup_bucket=play_data["dedup_bucket"],
            confidence=play_data.get("confidence"),
            title=play_data["title"],
            artist=play_data["artist"],
            album=play_data.get("album"),
            artwork_url=play_data.get("artwork_url"),
            stream_name=play_data["stream_name"],
        )
        play_records.append(play_record)

    # Handle CSV format
    if format.lower() == "csv":
        return generate_csv_response(play_records, target_date, stream)

    # Return JSON response
    return PlaysResponse(
        plays=play_records,
        total_count=len(play_records),
        date=date,
        stream=stream,
    )


def generate_csv_response(
    plays: list[PlayRecord], target_date: date, stream: str
) -> Response:
    """Generate CSV response for plays data."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            "Time (PT)",
            "Title",
            "Artist",
            "Album",
            "Stream",
            "Confidence",
            "Track ID",
            "UTC Timestamp",
        ]
    )

    # Write data rows
    for play in plays:
        writer.writerow(
            [
                play.recognized_at_pt,
                play.title,
                play.artist,
                play.album or "",
                play.stream_name,
                f"{play.confidence:.3f}" if play.confidence is not None else "",
                play.track_id,
                play.recognized_at_utc.isoformat(),
            ]
        )

    csv_content = output.getvalue()
    output.close()

    # Generate filename
    stream_suffix = f"_{stream}" if stream != "all" else "_all"
    filename = f"plays_{target_date.isoformat()}{stream_suffix}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_view(request: Request):
    """Diagnostics view - showing recent recognitions."""
    config: Config = request.app.state.config
    templates = request.app.state.templates

    # Get available streams from config
    streams = []
    for i in range(1, config.stream_count + 1):
        stream_config = getattr(config, f"stream_{i}", None)
        if stream_config and stream_config.enabled:
            streams.append(stream_config.name)

    return templates.TemplateResponse(
        request,
        "diagnostics.html",
        {
            "streams": streams,
        },
    )


@router.get("/api/recognitions", response_model=RecognitionsResponse)
async def get_recognitions(
    request: Request,
    limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
    stream: str | None = Query(None, description="Stream name filter"),
    provider: str | None = Query(None, description="Provider filter"),
):
    """Get recent recognition records."""
    config: Config = request.app.state.config

    # Validate stream name if provided
    if stream:
        valid_streams = []
        for i in range(1, config.stream_count + 1):
            stream_config = getattr(config, f"stream_{i}", None)
            if stream_config and stream_config.enabled:
                valid_streams.append(stream_config.name)

        if stream not in valid_streams:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stream '{stream}'. Valid streams: {valid_streams}",
            )

    # Validate provider if provided
    if provider and provider not in ["shazam", "acoustid"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{provider}'. Valid providers: shazam, acoustid",
        )

    # Query recognitions from database
    recognition_repo = RecognitionRepository(config.db_path)
    recognitions_data = await recognition_repo.get_recent_recognitions(
        limit=limit, stream_name=stream, provider=provider
    )

    # Convert to RecognitionRecord models with PT time conversion
    recognition_records = []
    for rec_data in recognitions_data:
        # Parse datetime strings back to datetime objects
        recognized_at_utc = datetime.fromisoformat(
            rec_data["recognized_at_utc"].replace("Z", "+00:00")
        )
        window_start_utc = None
        window_end_utc = None

        if rec_data.get("window_start_utc"):
            window_start_utc = datetime.fromisoformat(
                rec_data["window_start_utc"].replace("Z", "+00:00")
            )
        if rec_data.get("window_end_utc"):
            window_end_utc = datetime.fromisoformat(
                rec_data["window_end_utc"].replace("Z", "+00:00")
            )

        recognition_record = RecognitionRecord(
            id=rec_data["id"],
            stream_id=rec_data["stream_id"],
            stream_name=rec_data["stream_name"],
            provider=rec_data["provider"],
            recognized_at_utc=recognized_at_utc,
            recognized_at_pt=convert_utc_to_pt(recognized_at_utc),
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
            track_id=rec_data.get("track_id"),
            title=rec_data.get("title"),
            artist=rec_data.get("artist"),
            confidence=rec_data.get("confidence"),
            latency_ms=rec_data.get("latency_ms"),
            error_message=rec_data.get("error_message"),
            has_raw_response=rec_data.get("raw_response") is not None,
        )
        recognition_records.append(recognition_record)

    return RecognitionsResponse(
        recognitions=recognition_records,
        total_count=len(recognition_records),
        stream=stream,
        provider=provider,
    )


@router.get("/api/recognitions/{recognition_id}/raw")
async def get_recognition_raw(
    request: Request,
    recognition_id: int,
):
    """Get raw JSON response for a recognition record."""
    config: Config = request.app.state.config

    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            "SELECT raw_response FROM recognitions WHERE id = ?", (recognition_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Recognition not found")

        raw_response = row[0]
        if not raw_response:
            raise HTTPException(
                status_code=404, detail="No raw response available for this recognition"
            )

        try:
            import json

            parsed_response = json.loads(raw_response)
            return parsed_response
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail="Invalid JSON in raw response") from e


@router.post("/internal/reload")
async def reload_config(request: Request):
    """Reload configuration and restart workers."""
    worker_manager: WorkerManager = request.app.state.worker_manager

    try:
        # Stop current workers
        await worker_manager.stop()

        # Reload config
        new_config = Config()
        request.app.state.config = new_config

        # Start workers with new config
        worker_manager.config = new_config
        await worker_manager.start()

        return {
            "status": "reloaded",
            "message": "Configuration reloaded and workers restarted",
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to reload configuration: {str(e)}"
        ) from e
