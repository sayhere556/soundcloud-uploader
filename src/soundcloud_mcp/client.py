"""SoundCloud API client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from .config import API_BASE
from .oauth import OAuthError, get_valid_access_token


class SoundCloudClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=httpx.Timeout(30.0, read=300.0),
            headers={"accept": "application/json; charset=utf-8"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _auth_headers(self) -> dict[str, str]:
        token = await get_valid_access_token()
        return {"Authorization": f"OAuth {token}"}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(await self._auth_headers())
        response = await self._http.request(method, path, headers=headers, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"SoundCloud API {path} {response.status_code}: {response.text[:500]}")
        if response.content:
            return response.json()
        return None

    async def get_me(self) -> dict[str, Any]:
        return await self._request("GET", "/me")

    async def list_my_tracks(self, *, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request("GET", "/me/tracks", params={"limit": limit, "linked_partitioning": "true"})
        if isinstance(data, list):
            return data
        return data.get("collection", data)

    async def get_track(self, track_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/tracks/{track_id}")

    async def upload_track(
        self,
        *,
        file_path: str,
        title: str,
        description: str | None = None,
        genre: str | None = None,
        tag_list: str | None = None,
        sharing: str = "public",
        license: str | None = None,
        artwork_path: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        data: dict[str, str] = {
            "track[title]": title,
            "track[sharing]": sharing,
        }
        if description:
            data["track[description]"] = description
        if genre:
            data["track[genre]"] = genre
        if tag_list:
            data["track[tag_list]"] = tag_list
        if license:
            data["track[license]"] = license

        files: dict[str, Any] = {
            "track[asset_data]": (path.name, path.read_bytes(), "application/octet-stream"),
        }
        if artwork_path:
            art = Path(artwork_path).expanduser()
            if art.exists():
                files["track[artwork_data]"] = (art.name, art.read_bytes(), "image/jpeg")

        headers = await self._auth_headers()
        response = await self._http.post("/tracks", data=data, files=files, headers=headers)
        if not response.is_success:
            raise RuntimeError(f"Upload failed ({response.status_code}): {response.text[:500]}")
        return response.json()

    async def update_track(
        self,
        track_id: int,
        *,
        title: str | None = None,
        description: str | None = None,
        genre: str | None = None,
        tag_list: str | None = None,
        sharing: str | None = None,
        artwork_path: str | None = None,
        release: str | None = None,
        label_name: str | None = None,
    ) -> dict[str, Any]:
        track: dict[str, str] = {}
        if title is not None:
            track["title"] = title
        if description is not None:
            track["description"] = description
        if genre is not None:
            track["genre"] = genre
        if tag_list is not None:
            track["tag_list"] = tag_list
        if sharing is not None:
            track["sharing"] = sharing
        if release is not None:
            track["release"] = release
        if label_name is not None:
            track["label_name"] = label_name

        if artwork_path:
            art = Path(artwork_path).expanduser()
            if not art.exists():
                raise FileNotFoundError(f"Artwork not found: {art}")
            mime = "image/png" if art.suffix.lower() == ".png" else "image/jpeg"
            headers = await self._auth_headers()
            data = {f"track[{k}]": v for k, v in track.items()}
            files = {"track[artwork_data]": (art.name, art.read_bytes(), mime)}
            response = await self._http.put(f"/tracks/{track_id}", data=data, files=files, headers=headers)
            if not response.is_success:
                raise RuntimeError(f"Update failed ({response.status_code}): {response.text[:500]}")
            return response.json()

        if not track:
            raise ValueError("No fields to update")
        return await self._request("PUT", f"/tracks/{track_id}", json={"track": track})

    async def create_playlist(
        self,
        *,
        title: str,
        track_ids: list[int],
        description: str | None = None,
        sharing: str = "public",
        artwork_path: str | None = None,
    ) -> dict[str, Any]:
        if not track_ids:
            raise ValueError("track_ids required")

        payload: dict[str, Any] = {
            "playlist": {
                "title": title,
                "sharing": sharing,
                "tracks": [{"id": str(tid)} for tid in track_ids],
            }
        }
        if description:
            payload["playlist"]["description"] = description

        playlist = await self._request("POST", "/playlists", json=payload)

        if artwork_path:
            art = Path(artwork_path).expanduser()
            if not art.exists():
                raise FileNotFoundError(f"Artwork not found: {art}")
            mime = "image/png" if art.suffix.lower() == ".png" else "image/jpeg"
            playlist_id = playlist["id"]
            headers = await self._auth_headers()
            data = {f"playlist[{k}]": v for k, v in {"title": title, "sharing": sharing}.items()}
            if description:
                data["playlist[description]"] = description
            files = {"playlist[artwork_data]": (art.name, art.read_bytes(), mime)}
            response = await self._http.put(f"/playlists/{playlist_id}", data=data, files=files, headers=headers)
            if not response.is_success:
                raise RuntimeError(
                    f"Playlist artwork update failed ({response.status_code}): {response.text[:500]}"
                )
            playlist = response.json()

        return playlist

    async def delete_track(self, track_id: int) -> None:
        await self._request("DELETE", f"/tracks/{track_id}")


_client: SoundCloudClient | None = None


def get_client() -> SoundCloudClient:
    global _client
    if _client is None:
        _client = SoundCloudClient()
    return _client
