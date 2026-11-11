from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    # empty ${VAR} values from docker-compose fall back to the defaults below
    # /config/jellyfin.env (JELLYFIN_API_KEY) is written by the setup service; missing files are skipped
    model_config = SettingsConfigDict(env_file=(".env", "/config/jellyfin.env"), env_ignore_empty=True)

    bot_token: str
    qbit_host: str = "http://qbittorrent:8080"
    qbit_username: str = "admin"
    qbit_password: str
    download_path: str = "/downloads"
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    history_limit: int = 20
    history_db_path: str = "/data/history.db"
    qbit_keywords: str = "torrent,magnet,download,upload,seed,seeding,peer,tracker,ratio,pause,resume,скачать,торрент,раздача"
    jellyfin_keywords: str = "jellyfin,movie,series,episode,season,show,stream,media,library,subtitle,poster,metadata,watch,фильм,сериал,эпизод,смотреть,постер"
    qbit_mcp_url: str = "http://qbittorrent-mcp:3000/sse"
    jellyfin_mcp_url: str = "http://jellyfin-mcp:8080/mcp"
    mcp_http_token: str
    jellyfin_url: str = "http://jellyfin:8096"
    jellyfin_api_key: str = ""
    acestream_url: str = "http://acestream:6878"
    acestream_playlist: str = "/config/acestream/channels.m3u"

    @property
    def gemini_models(self) -> list[str]:
        return _csv(self.gemini_model)

    @property
    def qbit_keyword_list(self) -> list[str]:
        return _csv(self.qbit_keywords.lower())

    @property
    def jellyfin_keyword_list(self) -> list[str]:
        return _csv(self.jellyfin_keywords.lower())


settings = Settings()
