from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    qbit_host: str = "http://qbittorrent:8080"
    qbit_username: str = "admin"
    qbit_password: str
    download_path: str = "/downloads"
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    history_limit: int = 20
    qbit_keywords: str = "torrent,magnet,download,upload,seed,seeding,peer,tracker,ratio,pause,resume,скачать,торрент,раздача"
    jellyfin_keywords: str = "jellyfin,movie,series,episode,season,show,stream,media,library,subtitle,poster,metadata,watch,фильм,сериал,эпизод,смотреть,постер"

    @property
    def gemini_models(self) -> list[str]:
        return [m.strip() for m in self.gemini_model.split(",") if m.strip()]

    @property
    def qbit_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.qbit_keywords.split(",") if k.strip()]

    @property
    def jellyfin_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.jellyfin_keywords.split(",") if k.strip()]
    qbit_mcp_url: str = "http://qbittorrent-mcp:3000/sse"
    jellyfin_mcp_url: str = "http://jellyfin-mcp:8080/mcp"
    mcp_http_token: str
    history_db_path: str = "/data/history.db"

    class Config:
        env_file = ".env"


settings = Settings()
