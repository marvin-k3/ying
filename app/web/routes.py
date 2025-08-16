"""Web routes for the RTSP Music Tagger."""

import csv
import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from ..config import Config
from ..db.repo import PlayRepository
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
    confidence: Optional[float]
    title: str
    artist: str
    album: Optional[str]
    artwork_url: Optional[str]
    stream_name: str


class PlaysResponse(BaseModel):
    """Response model for plays API."""
    plays: List[PlayRecord]
    total_count: int
    date: str
    stream: str


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
        }
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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    
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
                detail=f"Invalid stream '{stream_filter}'. Valid streams: {valid_streams}"
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


def generate_csv_response(plays: List[PlayRecord], target_date: date, stream: str) -> Response:
    """Generate CSV response for plays data."""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        "Time (PT)",
        "Title",
        "Artist", 
        "Album",
        "Stream",
        "Confidence",
        "Track ID",
        "UTC Timestamp",
    ])
    
    # Write data rows
    for play in plays:
        writer.writerow([
            play.recognized_at_pt,
            play.title,
            play.artist,
            play.album or "",
            play.stream_name,
            f"{play.confidence:.3f}" if play.confidence is not None else "",
            play.track_id,
            play.recognized_at_utc.isoformat(),
        ])
    
    csv_content = output.getvalue()
    output.close()
    
    # Generate filename
    stream_suffix = f"_{stream}" if stream != "all" else "_all"
    filename = f"plays_{target_date.isoformat()}{stream_suffix}.csv"
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


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
        
        return {"status": "reloaded", "message": "Configuration reloaded and workers restarted"}
    
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to reload configuration: {str(e)}"
        )
