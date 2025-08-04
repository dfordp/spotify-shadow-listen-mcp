python
import os
import json
import asyncio
import time
import random
import httpx

from typing import Annotated, Dict, Any, List
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import ErrorData, McpError
from mcp.server.auth.provider import AccessToken
from mcp.types import INTERNAL_ERROR, TextContent
from pydantic import BaseModel, Field

# ==== Load environment ==== 
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==== Configuration ==== 
SPOTIFY_CLIENT_ID     = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REFRESH_TOKEN         = os.getenv("SPOTIFY_REFRESH_TOKEN")
TOKEN                 = os.getenv("MCP_BEARER_TOKEN", "shadow-spotify-token")

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
    API_BASE  = "https://api.spotify.com/v1"
    _access_token: str = ""
    _expires_at: float  = 0.0

    @classmethod
    async def ensure_token(cls) -> str:
        if time.time() < cls._expires_at - 60:
            return cls._access_token
        data = {
            "grant_type":    "refresh_token",
            "refresh_token": REFRESH_TOKEN,
            "client_id":     SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(cls.TOKEN_URL, data=data)
            if r.status_code != 200:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message="Spotify auth failed"))
            resp = r.json()
            cls._access_token = resp["access_token"]
            cls._expires_at   = time.time() + resp.get("expires_in", 3600)
            return cls._access_token

    @classmethod
    async def get(cls, path: str, params: dict = None) -> Any:
        token = await cls.ensure_token()
        url = f"{cls.API_BASE}/{path}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, params=params)
            if r.status_code >= 400:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Spotify GET {path} failed"))
            return r.json()

    @classmethod
    async def post(cls, path: str, json_body: dict) -> Any:
        token = await cls.ensure_token()
        url = f"{cls.API_BASE}/{path}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, headers=headers, json=json_body)
            if r.status_code >= 400:
                raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Spotify POST {path} failed"))
            return r.json()

# ==== Tool Metadata ==== 
class RichToolDescription(BaseModel):
    description: str
    use_when:    str
    side_effects: str | None

# ==== Server Init ==== 
mcp = FastMCP("ShadowFM Spotify Companion", auth=SimpleBearerAuthProvider(TOKEN))

def tool_desc(desc, use, side=None):
    return RichToolDescription(description=desc, use_when=use, side_effects=side).model_dump_json()

# === Basic Insight Tools ===
@mcp.tool(description=tool_desc(
    "Analyze your listening shift between two periods.",
    "You want to see how your music taste has changed over time.",
    "Fetches top tracks and computes valence differences."
))
async def analyze_listening_shift(
    start_range: Annotated[str, Field(description="short_term|medium_term|long_term")],
    end_range:   Annotated[str, Field(description="short_term|medium_term|long_term")]
) -> List[TextContent]:
    before = await SpotifyAPI.get("me/top/tracks", {"time_range": start_range, "limit": 20})
    after  = await SpotifyAPI.get("me/top/tracks", {"time_range": end_range,   "limit": 20})
    b_feats = await SpotifyAPI.get("audio-features", {"ids": ",".join([t["id"] for t in before.get("items",[])])})
    a_feats = await SpotifyAPI.get("audio-features", {"ids": ",".join([t["id"] for t in after.get("items",[])])})
    avg_b = sum(f.get("valence",0) for f in b_feats.get("audio_features",[])) / len(b_feats.get("audio_features",[]))
    avg_a = sum(f.get("valence",0) for f in a_feats.get("audio_features",[])) / len(a_feats.get("audio_features",[]))
    shift = avg_a - avg_b
    vibe  = "more upbeat" if shift>0.1 else "more mellow" if shift<-0.1 else "mostly stable"
    return [TextContent(type="text", text=json.dumps({"shift":round(shift,2), "vibe": vibe}, indent=2))]

@mcp.tool(description=tool_desc(
    "Get your listener identity and subculture match.",
    "You want a fun typology based on your listening profile.",
    "Aggregates genres into a persona label."
))
async def get_listener_identity() -> List[TextContent]:
    data = await SpotifyAPI.get("me/top/tracks", {"time_range":"medium_term","limit":30})
    counts: Dict[str,int]={}
    for t in data.get("items",[]):
        for a in t.get("artists",[]):
            for g in await SpotifyAPI.get("artists/"+a["id"]):
                counts[g]=counts.get(g,0)+1
    top5=sorted(counts.items(),key=lambda x:x[1],reverse=True)[:5]
    persona_map={"pop":"Pop Enthusiast","rock":"Rock Rebel","jazz":"Smooth Jazz Aficionado"}
    persona=persona_map.get(top5[0][0],"Eclectic Nomad")
    return [TextContent(type="json", text=json.dumps({"persona":persona,"top_genres":top5},indent=2))]

@mcp.tool(description=tool_desc(
    "Predict your future listening based on trend.",
    "You want to see where your music taste is going.",
    None
))
async def predict_future_taste() -> List[TextContent]:
    short=await SpotifyAPI.get("me/top/tracks",{"time_range":"short_term","limit":10})
    long=await SpotifyAPI.get("me/top/tracks",{"time_range":"long_term","limit":10})
    s_ids=[t["id"] for t in short.get("items",[])]
    l_ids=[t["id"] for t in long.get("items",[])]
    s_feats=await SpotifyAPI.get("audio-features",{"ids":",".join(s_ids)})
    l_feats=await SpotifyAPI.get("audio-features",{"ids":",".join(l_ids)})
    avg_s=sum(f.get("energy",0) for f in s_feats.get("audio_features",[]))/len(s_feats.get("audio_features",[]))
    avg_l=sum(f.get("energy",0) for f in l_feats.get("audio_features",[]))/len(l_feats.get("audio_features",[]))
    delta=avg_s-avg_l
    forecast="getting hyped" if delta>0.1 else "winding down" if delta<-0.1 else "equilibrium"
    return [TextContent(type="text", text=json.dumps({"energy_trend":forecast},indent=2))]

# === Core Spotify Features ===
@mcp.tool(description=tool_desc(
    "Search tracks by keyword.",
    "Find tracks matching a query.",
    None
))
async def search_tracks(q: Annotated[str,Field(description="Query text")], limit:Annotated[int,Field(default=10)]) -> List[TextContent]:
    data=await SpotifyAPI.get("search",{"q":q,"type":"track","limit":limit})
    return [TextContent(type="json", text=json.dumps(data.get("tracks",{}),indent=2))]

@mcp.tool(description=tool_desc(
    "Get user playlists.",
    "List your Spotify playlists.",
    None
))
async def get_user_playlists(limit:Annotated[int,Field(default=20)]) -> List[TextContent]:
    data=await SpotifyAPI.get("me/playlists",{"limit":limit})
    return [TextContent(type="json", text=json.dumps(data,indent=2))]

@mcp.tool(description=tool_desc(
    "Get playlist tracks.",
    "Fetch tracks from a playlist.",
    None
))
async def get_playlist_tracks(playlist_id:Annotated[str,Field(description="Playlist ID")], limit:Annotated[int,Field(default=20)]) -> List[TextContent]:
    data=await SpotifyAPI.get(f"playlists/{playlist_id}/tracks",{"limit":limit})
    return [TextContent(type="json", text=json.dumps(data,indent=2))]

@mcp.tool(description=tool_desc(
    "Create a new playlist.",
    "Create a playlist in your account.",
    None
))
async def create_playlist(name:Annotated[str,Field(description="Playlist name")], description:Annotated[str,Field(default="")]) -> List[TextContent]:
    user=await SpotifyAPI.get("me")
    body={"name":name,"description":description,"public":False}
    data=await SpotifyAPI.post(f"users/{user['id']}/playlists",body)
    return [TextContent(type="json", text=json.dumps(data,indent=2))]

@mcp.tool(description=tool_desc(
    "Add tracks to a playlist.",
    "Add track URIs to a playlist.",
    None
))
async def add_tracks_to_playlist(playlist_id:Annotated[str,Field(description="Playlist ID")], uris:Annotated[List[str],Field(description="Track URIs")]) -> List[TextContent]:
    data=await SpotifyAPI.post(f"playlists/{playlist_id}/tracks",{"uris":uris})
    return [TextContent(type="json", text=json.dumps(data,indent=2))]

# ==== Run Server ==== 
async def main():
    print("🚀 ShadowFM Spotify Companion MCP Server starting...")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=9090)

if __name__ == "__main__":
    asyncio.run(main())

