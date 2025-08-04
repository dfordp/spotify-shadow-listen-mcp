from typing import Annotated, Dict, Any, List
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import ErrorData, McpError
from mcp.server.auth.provider import AccessToken
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, TextContent
from pydantic import BaseModel, Field
import os
import asyncio
import httpx
import time
import json
import random

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==== Configuration ====
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN")
TOKEN = os.getenv("MCP_BEARER_TOKEN", "shadow-spotify-token")

# ==== Auth Provider ====
class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(public_key=k.public_key, jwks_uri=None, issuer=None, audience=None)
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(token=token, client_id="shadow-listener", scopes=[], expires_at=None)
        return None

# ==== Spotify API Helper ====
class SpotifyAPI:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"
    _access_token: str = ""
    _expires_at: float = 0.0

    @classmethod
    async def ensure_token(cls) -> str:
        if time.time() < cls._expires_at - 60:
            return cls._access_token
        data = {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(cls.TOKEN_URL, data=data)
            if r.status_code != 200:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message="Spotify auth failed"))
            resp = r.json()
            cls._access_token = resp["access_token"]
            cls._expires_at = time.time() + resp.get("expires_in", 3600)
            return cls._access_token

    @classmethod
    async def get_top_tracks(cls, time_range: str = "medium_term", limit: int = 20) -> List[Dict[str, Any]]:
        token = await cls.ensure_token()
        url = f"{cls.API_BASE}/me/top/tracks?time_range={time_range}&limit={limit}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message="Failed fetching top tracks"))
            return r.json().get("items", [])

    @classmethod
    async def get_audio_features(cls, track_ids: List[str]) -> List[Dict[str, Any]]:
        token = await cls.ensure_token()
        url = f"{cls.API_BASE}/audio-features"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"ids": ",".join(track_ids)}
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code != 200:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message="Failed fetching audio features"))
            return r.json().get("audio_features", [])

    @classmethod
    async def get_artist_genres(cls, artist_id: str) -> List[str]:
        token = await cls.ensure_token()
        url = f"{cls.API_BASE}/artists/{artist_id}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return []
            return r.json().get("genres", [])

# ==== Metadata for Tools ====
class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None

# ==== MCP Server Setup ====
mcp = FastMCP("Spotify Shadow Listener MCP", auth=SimpleBearerAuthProvider(TOKEN))

# ==== Tools ====
@mcp.tool(description=RichToolDescription(
    description="Analyze your listening shift between two periods.",
    use_when="You want to see how your music taste has changed over time.",
    side_effects="Fetches your top tracks and computes feature differences."
).json())
async def analyze_listening_shift(
    start_range: Annotated[str, Field(description="Start time range: short_term|medium_term|long_term")],
    end_range: Annotated[str, Field(description="End time range: short_term|medium_term|long_term")]
) -> List[TextContent]:
    before = await SpotifyAPI.get_top_tracks(start_range)
    after = await SpotifyAPI.get_top_tracks(end_range)
    before_ids = [t['id'] for t in before]
    after_ids = [t['id'] for t in after]
    before_feats = await SpotifyAPI.get_audio_features(before_ids)
    after_feats = await SpotifyAPI.get_audio_features(after_ids)
    avg_before = sum(f.get('valence', 0) for f in before_feats) / len(before_feats)
    avg_after = sum(f.get('valence', 0) for f in after_feats) / len(after_feats)
    shift = avg_after - avg_before
    vibe = "more upbeat" if shift > 0.1 else "more mellow" if shift < -0.1 else "mostly stable"
    message = f"Your average vibe shifted by {shift:.2f} between {start_range} and {end_range}, indicating you're becoming {vibe}."
    return [TextContent(type="text", text=json.dumps({"shift_message": message}, indent=2))]

@mcp.tool(description=RichToolDescription(
    description="Get your listener identity and subculture match.",
    use_when="You want a fun typology based on your listening profile.",
    side_effects="Fetches top genres and maps to a persona label."
).json())
async def get_listener_identity() -> List[TextContent]:
    tracks = await SpotifyAPI.get_top_tracks("medium_term", limit=30)
    genre_counts: Dict[str, int] = {}
    for track in tracks:
        for artist in track.get("artists", []):
            genres = await SpotifyAPI.get_artist_genres(artist["id"])
            for g in genres:
                genre_counts[g] = genre_counts.get(g, 0) + 1
    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
    dominant = top_genres[0][0] if top_genres else "unknown"
    persona_map = {
        "synthwave": "Dreamy Synthwave Wizard",
        "trap": "Nocturnal Basshead",
        "indie rock": "Melancholy Coffee Shop Poet",
        "k-pop": "Bubblegum Daydreamer",
        "classical": "Timeless Virtuoso",
        "jazz": "Cool Cat Connoisseur",
        "metal": "Thunderhead Rebel",
        "edm": "Neon Rave Chaser",
        "folk": "Nature-Strumming Wanderer",
        "unknown": "Eclectic Nomad"
    }
    persona = persona_map.get(dominant, "Eclectic Nomad")
    quirks = [
        "You probably wear headphones in the shower.",
        "Your Discover Weekly has existential crises.",
        "Your playlists are better than therapy.",
        "You judge people by their skip rate."
    ]
    return [TextContent(type="text", text=json.dumps({
        "identity": persona,
        "top_genres": top_genres[:5],
        "quirk": random.choice(quirks)
    }, indent=2))]

@mcp.tool(description=RichToolDescription(
    description="Predict your future listening based on trend.",
    use_when="You want to see where your music taste is going.",
    side_effects=None
).json())
async def predict_future_taste() -> List[TextContent]:
    short = await SpotifyAPI.get_top_tracks("short_term", limit=10)
    long = await SpotifyAPI.get_top_tracks("long_term", limit=10)
    s_ids = [t['id'] for t in short]
    l_ids = [t['id'] for t in long]
    s_feats = await SpotifyAPI.get_audio_features(s_ids)
    l_feats = await SpotifyAPI.get_audio_features(l_ids)
    avg_s = sum(f.get('energy', 0) for f in s_feats) / len(s_feats)
    avg_l = sum(f.get('energy', 0) for f in l_feats) / len(l_feats)
    delta = avg_s - avg_l
    forecast = "🔥 you're getting hyped" if delta > 0.1 else "🧘 you're winding down" if delta < -0.1 else "🎧 vibe equilibrium"
    return [TextContent(type="text", text=json.dumps({"energy_forecast": forecast, "delta_energy": round(delta, 3)}, indent=2))]

# ==== Run ====
async def main():
    print("🚀 Spotify Shadow Listener MCP Server starting...")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=9090)

if __name__ == "__main__":
    asyncio.run(main())
