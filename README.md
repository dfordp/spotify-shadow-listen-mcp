# 🎧 Spotify Shadow Listener MCP

A FastMCP-based AI agent server that analyzes your Spotify listening history in a playful and insightful way.  
It reveals your **listener identity**, analyzes your **taste shifts**, and even **predicts future music trends**—all without requiring full Spotify Premium access.

---

## ✨ Features

- 🔄 **Listening Shift Analyzer** – Track how your musical vibe has evolved across time periods.
- 🧠 **Listener Identity Tool** – Get your subculture persona and top genres.
- 🔮 **Future Taste Predictor** – Forecast where your music energy is heading.
- 🧭 **Smart Track Search** – Use GPT to help you search tracks via mood or situation.
- 🗂 **Your Playlists Explorer** – Get all your playlists and dig into what’s inside.
- 🧱 **Playlist Builder** – Create and add tracks to Spotify playlists using natural queries.

---

## 🛠 Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/spotify-shadow-listener-mcp.git
cd spotify-shadow-listener-mcp
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a `.env` file

```bash
cp .env.example .env
```

Then fill in the `.env` file with your Spotify credentials:

- Create an app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/applications)
- Use the **Authorization Code Flow** to generate a refresh token.

### 4. Run the MCP server

```bash
python spotify_shadow_listener_mcp.py
```

By default, it runs at `http://localhost:9090`.

---

## 🔐 Authentication

This MCP server uses a simple Bearer Token for authorization.
By default, it expects:

```http
Authorization: Bearer shadow-spotify-token
```

You can override this via the `.env` file:

```env
MCP_BEARER_TOKEN=your_custom_token
```

---

## 🧪 Example Tools

| Tool                      | Description                                                              |
| ------------------------- | ------------------------------------------------------------------------ |
| `analyze_listening_shift` | Compares your top tracks' valence between two time ranges.               |
| `get_listener_identity`   | Generates a fun listener persona based on your genre and mood profile.   |
| `predict_future_taste`    | Projects your energy trend using recent vs long-term listening patterns. |
| `search_tracks`           | Search Spotify using mood or artist/style descriptors.                   |
| `get_user_playlists`      | Lists all your Spotify playlists.                                        |
| `get_playlist_tracks`     | Shows what's inside a selected playlist.                                 |
| `create_playlist`         | Creates a new playlist in your account.                                 |
| `add_tracks_to_playlist`  | Adds specific tracks into one of your playlists.                         |

---

## 📦 Built With

- 🧠 [FastMCP](https://github.com/fixie-ai/fastmcp)
- 🎧 [Spotify Web API](https://developer.spotify.com/documentation/web-api/)
- 🔒 Bearer token authentication

---

## 📝 License

MIT License

---

Built for fun and insight by music lovers ❤️🎶  
*Not affiliated with Spotify.*
