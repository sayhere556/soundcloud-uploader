"""SoundCloud MCP Server."""

import atexit
import asyncio
import json

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .client import get_client

load_dotenv()

mcp = FastMCP("soundcloud_mcp")


def _json(data) -> str:
    return json.dumps(data, indent=2, default=str)


class ListTracksInput(BaseModel):
    limit: int = Field(default=50, ge=1, le=200, description="Max tracks to return")


class TrackIdInput(BaseModel):
    track_id: int = Field(description="SoundCloud track ID")


class UploadTrackInput(BaseModel):
    file_path: str = Field(description="Path to audio file (MP3, WAV, FLAC, etc.)")
    title: str = Field(description="Track title")
    description: str | None = Field(default=None, description="Track description")
    genre: str | None = Field(default=None, description="Primary genre")
    tag_list: str | None = Field(default=None, description="Space-separated tags")
    sharing: str = Field(default="public", description="'public' or 'private'")
    license: str | None = Field(default=None, description="e.g. cc-by, all-rights-reserved")
    artwork_path: str | None = Field(default=None, description="Optional cover art image path")


class UpdateTrackInput(BaseModel):
    track_id: int = Field(description="SoundCloud track ID")
    title: str | None = None
    description: str | None = None
    genre: str | None = None
    tag_list: str | None = None
    sharing: str | None = None
    artwork_path: str | None = None
    release: str | None = Field(default=None, description="Album / release name")
    label_name: str | None = Field(default=None, description="Record label name")


class CreatePlaylistInput(BaseModel):
    title: str = Field(description="Playlist title")
    track_ids: list[int] = Field(description="SoundCloud track IDs in order")
    description: str | None = None
    sharing: str = Field(default="public", description="'public' or 'private'")
    artwork_path: str | None = Field(default=None, description="Optional cover art image path")


@mcp.tool(name="soundcloud_get_me")
async def soundcloud_get_me() -> str:
    """Get your authenticated SoundCloud profile."""
    return _json(await get_client().get_me())


@mcp.tool(name="soundcloud_list_my_tracks")
async def soundcloud_list_my_tracks(params: ListTracksInput) -> str:
    """List tracks uploaded to your SoundCloud account."""
    return _json(await get_client().list_my_tracks(limit=params.limit))


@mcp.tool(name="soundcloud_get_track")
async def soundcloud_get_track(params: TrackIdInput) -> str:
    """Get details for a specific track by ID."""
    return _json(await get_client().get_track(params.track_id))


@mcp.tool(name="soundcloud_upload_track")
async def soundcloud_upload_track(params: UploadTrackInput) -> str:
    """
    Upload an audio file to SoundCloud.

    Requires OAuth login (run soundcloud-mcp-auth once). Uses your Artist Pro API credentials.
    """
    track = await get_client().upload_track(
        file_path=params.file_path,
        title=params.title,
        description=params.description,
        genre=params.genre,
        tag_list=params.tag_list,
        sharing=params.sharing,
        license=params.license,
        artwork_path=params.artwork_path,
    )
    return _json({
        "id": track.get("id"),
        "title": track.get("title"),
        "permalink_url": track.get("permalink_url"),
        "sharing": track.get("sharing"),
        "state": track.get("state"),
        "track": track,
    })


@mcp.tool(name="soundcloud_update_track")
async def soundcloud_update_track(params: UpdateTrackInput) -> str:
    """Update metadata for an existing track."""
    return _json(await get_client().update_track(
        params.track_id,
        title=params.title,
        description=params.description,
        genre=params.genre,
        tag_list=params.tag_list,
        sharing=params.sharing,
        artwork_path=params.artwork_path,
        release=params.release,
        label_name=params.label_name,
    ))


@mcp.tool(name="soundcloud_create_playlist")
async def soundcloud_create_playlist(params: CreatePlaylistInput) -> str:
    """Create a SoundCloud playlist (album/set) with ordered tracks and optional cover art."""
    playlist = await get_client().create_playlist(
        title=params.title,
        track_ids=params.track_ids,
        description=params.description,
        sharing=params.sharing,
        artwork_path=params.artwork_path,
    )
    return _json({
        "id": playlist.get("id"),
        "title": playlist.get("title"),
        "permalink_url": playlist.get("permalink_url"),
        "track_count": playlist.get("track_count"),
        "playlist": playlist,
    })


@mcp.tool(name="soundcloud_delete_track")
async def soundcloud_delete_track(params: TrackIdInput) -> str:
    """Delete a track from your SoundCloud account."""
    await get_client().delete_track(params.track_id)
    return _json({"deleted": True, "track_id": params.track_id})


def main() -> None:
    def _cleanup():
        try:
            client = get_client()
            asyncio.get_event_loop().run_until_complete(client.close())
        except Exception:
            pass

    atexit.register(_cleanup)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
