from dataclasses import dataclass
from pathlib import Path
import os
import re


@dataclass(frozen=True)
class Settings:
    uri: str = ""
    database: str = "SECIngestion"
    user_agent: str = ""
    parser_version: str = "arelle-v1"
    allow_live: bool = True

    @classmethod
    def load(cls, env_file: str | None = None):
        if env_file:
            from dotenv import dotenv_values
            path = Path(env_file)
            if not path.is_file():
                raise ValueError("The requested env file does not exist")
            values = dotenv_values(path, interpolate=False)
        else:
            values = os.environ
        database = values.get("SEC_MONGODB_DATABASE", "SECIngestion")
        if database != "SECIngestion":
            raise ValueError("SEC_MONGODB_DATABASE must be SECIngestion; legacy databases are protected")
        return cls(uri=values.get("SEC_MONGODB_URI", ""), database=database,
                   user_agent=values.get("SEC_USER_AGENT", ""),
                   parser_version=values.get("SEC_PARSER_VERSION", "arelle-v1"),
                   allow_live=values.get("SEC_OFFLINE", "false").lower() != "true")

    def require_identity(self):
        if not re.fullmatch(r"[^\r\n]{3,160}\s[<(]?[^\s@<>()]+@[^\s@<>()]+\.[A-Za-z]{2,}[>)]?", self.user_agent):
            raise ValueError("SEC_USER_AGENT must contain your application name and a monitored contact email")
        if any(word in self.user_agent.lower() for word in ("example.com", "example.org", "apicaller@", "john doe", "placeholder")):
            raise ValueError("Replace the placeholder SEC_USER_AGENT with your own identity")
