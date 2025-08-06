    import os
    import json
    import asyncio
    import time
    import httpx
    import base64
    import urllib.parse

    from typing import Annotated, Dict, Any, List, Optional
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
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
    SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN")
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
            
            # For full access with user context (if refresh token available)
            if SPOTIFY_REFRESH_TOKEN:
                data = {
                    "grant_type": "refresh_token",
                    "refresh_token": SPOTIFY_REFRESH_TOKEN,
                }
                headers = {
                    "Authorization": f"Basic {base64.b64encode(f'{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}'.encode()).decode()}"
                }
            else:
                # Fallback to client credentials (limited access)
                data = {
                    "grant_type": "client_credentials",
                    "client_id": SPOTIFY_CLIENT_ID,
                    "client_secret": SPOTIFY_CLIENT_SECRET,
                }
                headers = {}
                
            async with httpx.AsyncClient() as client:
                try:
                    r = await client.post(cls.TOKEN_URL, data=data, headers=headers)
                    
                    if r.status_code != 200:
                        error_detail = f"HTTP {r.status_code}: {r.text}"
                        print(f"Spotify auth failed: {error_detail}")
                        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Spotify auth failed: {error_detail}"))
                    
                    resp = r.json()
                    cls._access_token = resp["access_token"]
                    cls._expires_at = time.time() + resp.get("expires_in", 3600)
                    return cls._access_token
                except httpx.RequestError as e:
                    error_msg = f"Connection error: {str(e)}"
                    print(error_msg)
                    raise McpError(ErrorData(code=INTERNAL_ERROR, message=error_msg))

        @classmethod
        async def get(cls, path: str, params: Optional[dict] = None) -> Any:
            token = await cls.ensure_token()
            url = f"{cls.API_BASE}/{path}"
            headers = {"Authorization": f"Bearer {token}"}
            
            # Debug logs
            print(f"Making GET request to: {url}")
            if params:
                print(f"With params: {params}")
            
            async with httpx.AsyncClient() as client:
                try:
                    r = await client.get(url, headers=headers, params=params)
                    
                    # Debug response
                    print(f"Response status: {r.status_code}")
                    
                    if r.status_code >= 400:
                        error_detail = f"HTTP {r.status_code}: {r.text}"
                        print(f"Spotify API error: {error_detail}")
                        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Spotify GET {path} failed: {error_detail}"))
                    
                    return r.json()
                except httpx.RequestError as e:
                    error_msg = f"Request error: {str(e)}"
                    print(error_msg)
                    raise McpError(ErrorData(code=INTERNAL_ERROR, message=error_msg))

        @classmethod
        async def post(cls, path: str, json_body: dict) -> Any:
            token = await cls.ensure_token()
            url = f"{cls.API_BASE}/{path}"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            
            # Debug logs
            print(f"Making POST request to: {url}")
            print(f"With body: {json.dumps(json_body)}")
            
            async with httpx.AsyncClient() as client:
                try:
                    r = await client.post(url, headers=headers, json=json_body)
                    
                    # Debug response
                    print(f"Response status: {r.status_code}")
                    
                    if r.status_code >= 400:
                        error_detail = f"HTTP {r.status_code}: {r.text}"
                        print(f"Spotify API error: {error_detail}")
                        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Spotify POST {path} failed: {error_detail}"))
                    
                    return r.json()
                except httpx.RequestError as e:
                    error_msg = f"Request error: {str(e)}"
                    print(error_msg)
                    raise McpError(ErrorData(code=INTERNAL_ERROR, message=error_msg))

    # ==== Tool Metadata ==== 
    class RichToolDescription(BaseModel):
        description: str
        use_when: str
        side_effects: str | None

    # ==== Server Init ==== 
    app = FastMCP("Spotify Music Explorer", auth=SimpleBearerAuthProvider(TOKEN))

    def tool_desc(desc, use, side=None):
        return RichToolDescription(description=desc, use_when=use, side_effects=side).model_dump_json()

    # === Core Spotify Features ===
    @app.tool(description=tool_desc("Search tracks by keyword.", "Find tracks matching query.", None))
    async def search_tracks(q: Annotated[str, Field(description="Query text")], limit: Annotated[int, Field(default=10)]) -> List[TextContent]:
        data = await SpotifyAPI.get("search", {"q": q, "type": "track", "limit": limit})
        return [TextContent(type="text", text=json.dumps(data.get("tracks", {}), indent=2))]

    @app.tool(description=tool_desc("Search artists by keyword.", "Find artists matching query.", None))
    async def search_artists(q: Annotated[str, Field(description="Query text")], limit: Annotated[int, Field(default=10)]) -> List[TextContent]:
        data = await SpotifyAPI.get("search", {"q": q, "type": "artist", "limit": limit})
        return [TextContent(type="text", text=json.dumps(data.get("artists", {}), indent=2))]

    @app.tool(description=tool_desc("Search albums by keyword.", "Find albums matching query.", None))
    async def search_albums(q: Annotated[str, Field(description="Query text")], limit: Annotated[int, Field(default=10)]) -> List[TextContent]:
        data = await SpotifyAPI.get("search", {"q": q, "type": "album", "limit": limit})
        return [TextContent(type="text", text=json.dumps(data.get("albums", {}), indent=2))]

    @app.tool(description=tool_desc("Get playlist details.", "Fetch playlist info.", None))
    async def get_playlist(playlist_id: Annotated[str, Field(description="Playlist ID")]) -> List[TextContent]:
        try:
            data = await SpotifyAPI.get(f"playlists/{playlist_id}")
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        except McpError as e:
            error_message = str(e)
            # Check if this is a 404 error
            if "404" in error_message and "Resource not found" in error_message:
                message = (
                    f"Unable to access playlist {playlist_id}. Spotify requires user authorization to access playlists.\n\n"
                    f"To fix this:\n"
                    f"1. You need to set up a refresh token with the proper scopes\n"
                    f"2. Add it to your .env file as SPOTIFY_REFRESH_TOKEN\n\n"
                    f"Alternative: Try searching for p  ublic playlists instead."
                )
                return [TextContent(type="text", text=message)]
            # For other errors, re-raise
            raise e

    @app.tool(description=tool_desc("Get playlist tracks.", "Fetch playlist items.", None))
    async def get_playlist_tracks(playlist_id: Annotated[str, Field(description="Playlist ID")], limit: Annotated[int, Field(default=20)]) -> List[TextContent]:
        try:
            data = await SpotifyAPI.get(f"playlists/{playlist_id}/tracks", {"limit": limit})
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        except McpError as e:
            error_message = str(e)
            # Check if this is a 404 error
            if "404" in error_message and "Resource not found" in error_message:
                message = (
                    f"Unable to access tracks for playlist {playlist_id}. Spotify requires user authorization to access playlist tracks.\n\n"
                    f"To fix this:\n"
                    f"1. You need to set up a refresh token with the proper scopes\n"
                    f"2. Add it to your .env file as SPOTIFY_REFRESH_TOKEN\n\n"
                    f"Alternative: Try searching for tracks directly or browse featured playlists."
                )
                return [TextContent(type="text", text=message)]
            # For other errors, re-raise
            raise e

    @app.tool(description=tool_desc("Get track details.", "Get detailed track info.", None))
    async def get_track(track_id: Annotated[str, Field(description="Track ID")]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"tracks/{track_id}")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    @app.tool(description=tool_desc("Get artist details.", "View artist info.", None))
    async def get_artist(artist_id: Annotated[str, Field(description="Artist ID")]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"artists/{artist_id}")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    @app.tool(description=tool_desc("Get artist's albums.", "View artist's discography.", None))
    async def get_artist_albums(artist_id: Annotated[str, Field(description="Artist ID")], limit: Annotated[int, Field(default=20)]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"artists/{artist_id}/albums", {"limit": limit})
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    @app.tool(description=tool_desc("Get artist's top tracks.", "View artist's popular songs.", None))
    async def get_artist_top_tracks(artist_id: Annotated[str, Field(description="Artist ID")], market: Annotated[str, Field(description="Market code", default="US")]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"artists/{artist_id}/top-tracks", {"market": market})
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    @app.tool(description=tool_desc("Get related artists.", "Find similar artists.", None))
    async def get_related_artists(artist_id: Annotated[str, Field(description="Artist ID")]) -> List[TextContent]:
        try:
            # First verify the artist exists
            try:
                artist_data = await SpotifyAPI.get(f"artists/{artist_id}")
                artist_name = artist_data.get("name", "")
                print(f"Found artist: {artist_name} with ID {artist_id}")
            except McpError as e:
                if "404" in str(e):
                    return [TextContent(type="text", text=f"Error: Artist with ID '{artist_id}' not found in Spotify database. Please check the ID and try again.")]
                else:
                    raise e
            
            # Now try to get related artists
            try:
                data = await SpotifyAPI.get(f"artists/{artist_id}/related-artists")
                return [TextContent(type="text", text=json.dumps(data, indent=2))]
            except McpError as e:
                # Fallback to search-based similar artists
                print(f"Related artists endpoint failed, using search fallback: {str(e)}")
                
                # Search for similar artists based on the name
                search_data = await SpotifyAPI.get("search", {"q": f"artist:{artist_name}", "type": "artist", "limit": 10})
                artists = search_data.get("artists", {}).get("items", [])
                
                # Filter out the original artist from results if present
                filtered_artists = [a for a in artists if a.get("id") != artist_id]
                
                if filtered_artists:
                    result = {"artists": filtered_artists}
                    return [TextContent(type="text", text=json.dumps(result, indent=2))]
                else:
                    return [TextContent(type="text", text=f"No related artists found for {artist_name} (ID: {artist_id})")]
        except Exception as e:
            print(f"Unexpected error in get_related_artists: {str(e)}")
            return [TextContent(type="text", text=f"Error finding related artists: {str(e)}")]

    @app.tool(description=tool_desc("Get album details.", "View album info.", None))
    async def get_album(album_id: Annotated[str, Field(description="Album ID")]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"albums/{album_id}")
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    @app.tool(description=tool_desc("Get album tracks.", "View tracks in an album.", None))
    async def get_album_tracks(album_id: Annotated[str, Field(description="Album ID")], limit: Annotated[int, Field(default=20)]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"albums/{album_id}/tracks", {"limit": limit})
        return [TextContent(type="text", text=json.dumps(data, indent=2))]

    @app.tool(description=tool_desc("Get recommendations.", "Get track recommendations.", None))
    async def get_recommendations(
        limit: Annotated[int, Field(default=10)], 
        seed_artists: Annotated[List[str], Field(description="Artist IDs")] = [],
        seed_tracks: Annotated[List[str], Field(description="Track IDs")] = [],
        seed_genres: Annotated[List[str], Field(description="Genre names")] = []
    ) -> List[TextContent]:
        params = {"limit": limit}
        if seed_artists: params["seed_artists"] = ",".join(seed_artists)
        if seed_tracks: params["seed_tracks"] = ",".join(seed_tracks)
        if seed_genres: params["seed_genres"] = ",".join(seed_genres)
        data = await SpotifyAPI.get("recommendations", params)
        return [TextContent(type="text", text=json.dumps(data.get("tracks", []), indent=2))]

    @app.tool(description=tool_desc("Get audio features.", "Retrieve audio features for tracks.", None))
    async def get_audio_features(track_ids: Annotated[List[str], Field(description="Track IDs")]) -> List[TextContent]:
        # Start with dummy features for common attributes if all API calls fail
        dummy_features = {
            "acousticness": "Information not available",
            "danceability": "Information not available",
            "energy": "Information not available",
            "instrumentalness": "Information not available",
            "key": "Information not available",
            "liveness": "Information not available",
            "loudness": "Information not available",
            "mode": "Information not available",
            "speechiness": "Information not available",
            "tempo": "Information not available",
            "time_signature": "Information not available",
            "valence": "Information not available"
        }
        
        try:
            # Try bulk endpoint first
            try:
                data = await SpotifyAPI.get("audio-features", {"ids": ",".join(track_ids[:50])})
                if data and "audio_features" in data:
                    return [TextContent(type="text", text=json.dumps(data["audio_features"], indent=2))]
            except McpError as e:
                print(f"Bulk audio features request failed: {str(e)}")
                
            # Try individual endpoints
            all_features = []
            for track_id in track_ids[:20]:  # Limit to first 20 to avoid too many requests
                track_info = {"id": track_id}
                
                # Get track details first for context
                try:
                    track_data = await SpotifyAPI.get(f"tracks/{track_id}")
                    track_info["track_name"] = track_data.get("name", "Unknown")
                    track_info["artist"] = track_data.get("artists", [{}])[0].get("name", "Unknown")
                    track_info["album"] = track_data.get("album", {}).get("name", "Unknown")
                    track_info["popularity"] = track_data.get("popularity", "Unknown")
                    track_info["duration_ms"] = track_data.get("duration_ms", "Unknown")
                except Exception as e:
                    print(f"Failed to get track info for {track_id}: {str(e)}")
                    
                # Try to get audio features
                try:
                    feature_data = await SpotifyAPI.get(f"audio-features/{track_id}")
                    if feature_data and not isinstance(feature_data, str):
                        # Combine track info and audio features
                        track_info.update(feature_data)
                        all_features.append(track_info)
                        continue
                except Exception as e:
                    print(f"Failed to get audio features for {track_id}: {str(e)}")
                
                # If we reach here, we couldn't get audio features
                # Add track info with dummy features
                track_info.update(dummy_features)
                track_info["note"] = "Audio features unavailable - API permission restrictions"
                all_features.append(track_info)
            
            if all_features:
                return [TextContent(type="text", text=json.dumps(all_features, indent=2))]
            
            # Fall back to explanation if all attempts fail
            message = (
                "⚠️ Unable to access audio features via Spotify API. This is likely due to:\n\n"
                "1. Permission restrictions with client credentials authentication\n"
                "2. The audio-features endpoint requires user authorization\n\n"
                "To fix this:\n"
                "- Set up a refresh token with the 'user-read-private' scope\n"
                "- Add it to your .env file as SPOTIFY_REFRESH_TOKEN\n\n"
                "For now, here's what audio features typically include:\n\n"
                "- danceability: How suitable a track is for dancing (0.0 to 1.0)\n"
                "- energy: Perceptual measure of intensity and activity (0.0 to 1.0)\n"
                "- valence: Musical positiveness conveyed by a track (0.0 to 1.0)\n"
                "- tempo: Estimated tempo in BPM\n"
                "- acousticness: Confidence measure of whether the track is acoustic (0.0 to 1.0)\n"
                "- instrumentalness: Predicts whether a track contains no vocals (0.0 to 1.0)\n"
                "- liveness: Detects presence of audience in the recording (0.0 to 1.0)\n"
                "- speechiness: Presence of spoken words in a track (0.0 to 1.0)"
            )
            return [TextContent(type="text", text=message)]
        
        except Exception as e:
            print(f"Unexpected error in get_audio_features: {str(e)}")
            return [TextContent(type="text", text=f"Error retrieving audio features: {str(e)}\n\nThis endpoint may require user authorization.")]
        
    @app.tool(description=tool_desc("Get audio analysis.", "Get detailed audio analysis for a track.", None))
    async def get_audio_analysis(track_id: Annotated[str, Field(description="Track ID")]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"audio-analysis/{track_id}")
        # Audio analysis data can be large, so we'll return a summary
        summary = {
            "track": data.get("track", {}),
            "sections_count": len(data.get("sections", [])),
            "segments_count": len(data.get("segments", [])),
            "beats_count": len(data.get("beats", [])),
            "bars_count": len(data.get("bars", []))
        }
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    @app.tool(description=tool_desc("Get available genre seeds.", "List genres for recommendations.", None))
    async def get_genre_seeds() -> List[TextContent]:
        try:
            data = await SpotifyAPI.get("recommendations/available-genre-seeds")
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        except McpError:
            # Fallback to hardcoded common genre seeds if the API call fails
            fallback_genres = {
                "genres": [
                    "acoustic", "afrobeat", "alt-rock", "alternative", "ambient", "blues",
                    "classical", "country", "dance", "electronic", "folk", "funk", "hip-hop",
                    "house", "indie", "jazz", "metal", "pop", "r-n-b", "reggae", "rock", "soul"
                ]
            }
            return [TextContent(type="text", text=json.dumps(fallback_genres, indent=2))]

    @app.tool(description=tool_desc("Get new releases.", "View latest album releases.", None))
    async def get_new_releases(limit: Annotated[int, Field(default=20)], country: Annotated[str, Field(default="US")]) -> List[TextContent]:
        data = await SpotifyAPI.get("browse/new-releases", {"limit": limit, "country": country})
        return [TextContent(type="text", text=json.dumps(data.get("albums", {}), indent=2))]

    @app.tool(description=tool_desc("Get featured playlists.", "View curated featured playlists.", None))
    async def get_featured_playlists(limit: Annotated[int, Field(default=20)], country: Annotated[str, Field(default="US")]) -> List[TextContent]:
        data = await SpotifyAPI.get("browse/featured-playlists", {"limit": limit, "country": country})
        return [TextContent(type="text", text=json.dumps(data.get("playlists", {}), indent=2))]

    @app.tool(description=tool_desc("Get categories.", "Browse content categories.", None))
    async def get_categories(limit: Annotated[int, Field(default=20)], country: Annotated[str, Field(default="US")]) -> List[TextContent]:
        data = await SpotifyAPI.get("browse/categories", {"limit": limit, "country": country})
        return [TextContent(type="text", text=json.dumps(data.get("categories", {}), indent=2))]

    @app.tool(description=tool_desc("Get category playlists.", "View playlists for a category.", None))
    async def get_category_playlists(category_id: Annotated[str, Field(description="Category ID")], limit: Annotated[int, Field(default=20)]) -> List[TextContent]:
        data = await SpotifyAPI.get(f"browse/categories/{category_id}/playlists", {"limit": limit})
        return [TextContent(type="text", text=json.dumps(data.get("playlists", {}), indent=2))]

    @app.tool(description=tool_desc("Compare tracks.", "Compare audio features between tracks.", None))
    async def compare_tracks(track_ids: Annotated[List[str], Field(description="Track IDs (2-5 tracks)")]) -> List[TextContent]:
        if not 2 <= len(track_ids) <= 5:
            return [TextContent(type="text", text="Please provide between 2 and 5 track IDs for comparison")]
        
        # Get features using individual requests to avoid 403 errors
        features = []
        tracks_info = []
        
        for track_id in track_ids:
            # Get track details first
            try:
                track_data = await SpotifyAPI.get(f"tracks/{track_id}")
                track_info = {
                    "id": track_id,
                    "name": track_data.get("name", "Unknown"),
                    "artist": track_data.get("artists", [{}])[0].get("name", "Unknown")
                }
                tracks_info.append(track_info)
                
                # Get audio features for this track
                try:
                    feature_data = await SpotifyAPI.get(f"audio-features/{track_id}")
                    if feature_data and not isinstance(feature_data, str):
                        features.append(feature_data)
                    else:
                        features.append(None)
                except:
                    features.append(None)
                    
            except:
                # If we can't get track details, use a placeholder
                tracks_info.append({
                    "id": track_id,
                    "name": "Unknown Track",
                    "artist": "Unknown Artist"
                })
                features.append(None)
        
        if not any(features) or len(features) < 2:
            return [TextContent(type="text", text="Could not retrieve audio features for the provided tracks. Please verify the track IDs and try again.")]
        
        # Prepare comparison data
        comparison = {}
        for feature_name in ["danceability", "energy", "valence", "tempo", "acousticness", "instrumentalness"]:
            comparison[feature_name] = {}
            for i, feature in enumerate(features):
                if i < len(tracks_info) and feature:  # Ensure we have track info and feature data
                    track_name = f"{tracks_info[i]['name']} by {tracks_info[i]['artist']}"
                    comparison[feature_name][track_name] = feature.get(feature_name)
        
        return [TextContent(type="text", text=json.dumps(comparison, indent=2))]

    # ==== Run Server ==== 
    async def main():
        print("🚀 Spotify Music Explorer MCP Server starting...")
        print(f"Using client ID: {SPOTIFY_CLIENT_ID}")
        print(f"Bearer token: {TOKEN}")
        print(f"Refresh token available: {'Yes' if SPOTIFY_REFRESH_TOKEN else 'No'}")
        
        # Validate Spotify credentials
        if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
            print("⚠️ WARNING: Missing Spotify API credentials. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env file.")
        
        try:
            # Attempt to get an access token before starting the server
            print("Authenticating with Spotify...")
            await SpotifyAPI.ensure_token()
            print("✅ Spotify authentication successful!")
            
            await app.run_async("streamable-http", host="0.0.0.0", port=9090)
        except Exception as e:
            print(f"❌ Server error: {e}")
            print("Check your Spotify credentials and try again.")

    if __name__ == "__main__":
        asyncio.run(main())