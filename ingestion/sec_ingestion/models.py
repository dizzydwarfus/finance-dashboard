from datetime import date
from calendar import monthrange
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

TERMINAL = {"completed", "partial_failed", "failed", "blocked", "cancelled", "superseded"}
ACTIVE = {"pending", "queued", "running", "paused_rate_limit"}


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")
    action: Literal["scrape", "refresh"] = "scrape"
    selection: Literal["latest", "range", "10-K", "10-Q", "company-facts"] = "latest"
    retryAccess: bool = False
    fromDate: date | None = None
    toDate: date | None = None

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_range(self):
        if self.selection == "range":
            if not self.fromDate or not self.toDate:
                raise ValueError("Choose both filing dates")
            if self.fromDate < date(2009, 1, 1) or self.toDate > date.today() or self.fromDate > self.toDate:
                raise ValueError("Choose an ordered filing-date range between 2009 and today")
            anniversary = self.fromDate.replace(year=self.fromDate.year + 5, day=min(self.fromDate.day, monthrange(self.fromDate.year + 5, self.fromDate.month)[1]))
            if self.toDate > anniversary:
                raise ValueError("A job can cover at most five years")
        elif self.fromDate or self.toDate:
            raise ValueError("Dates are supported only for range selection")
        if self.action == "scrape" and self.selection == "company-facts":
            raise ValueError("Company facts are an explicit refresh action")
        return self


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str, **details):
        self.status, self.code, self.message, self.details = status, code, message, details
        super().__init__(message)
