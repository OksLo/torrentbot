from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    qbit_host: str = "http://qbittorrent:8080"
    qbit_username: str = "admin"
    qbit_password: str
    download_path: str = "/downloads"
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    qbit_mcp_url: str = "http://qbittorrent-mcp:3000/sse"
    jellyfin_mcp_url: str = "http://jellyfin-mcp:8080/mcp"
    mcp_http_token: str
    history_db_path: str = "/data/history.db"

    class Config:
        env_file = ".env"


settings = Settings()
