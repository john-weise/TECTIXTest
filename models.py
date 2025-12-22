# models.py
from __future__ import annotations
from datetime import time
from pydantic import BaseModel, Field, validator,  field_validator, ConfigDict, StringConstraints
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Annotated
from log_config import setup_logging
import enum
from dataclasses import dataclass
import pandas as pd
import numpy as np



logger = setup_logging()






class LoginInput(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)

    @validator("username", pre=True)
    def reject_suspicious_username(cls, v: str) -> str:
        # any shell-/CLI-meta characters get logged and rejected
        if any(c in v for c in [';', '|', '&', '`', '$', '>', '<']):
            logger.warning(f"[SUSPICIOUS INPUT] Attempted username={v!r}")
            raise ValueError("Invalid characters in username")
        return v

class LoginResponse(BaseModel):
    success: bool
    user: Optional[str] = None
    error: Optional[str] = None
    two_factor_required: bool = False

class CreateUserInput(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)
    is_admin: bool = False

class DeleteUserInput(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)

class ProcessInput(BaseModel):
    system_id: int = Field(..., ge=1, le=99999)  # Must be a 1–5 digit integer

#2 factor auth models

CodeStr = Annotated[str, StringConstraints(min_length=1, max_length=32)]


class TwoFactorCodeInput(BaseModel):
    """Request model for submitting a 2FA code."""
    code: CodeStr


class StartTwoFactorEnrollmentResponse(BaseModel):
    """Response model for starting 2FA enrollment."""
    secret: str
    provisioning_uri: str
    recovery_codes: list[str]


class TwoFactorStatusResponse(BaseModel):
    """Response model for 2FA status."""
    enabled: bool
    configured: bool



def _dump(obj: BaseModel) -> Dict[str, Any]:
    # Pydantic v2 -> model_dump; v1 -> dict
    return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()


def _dump_json(obj: BaseModel) -> str:
    # Pydantic v2 -> model_dump_json; v1 -> json
    return obj.model_dump_json() if hasattr(obj, "model_dump_json") else obj.json()


@dataclass
class DataFramePayload:
    system_id: int
    source: str
    shape: Tuple[int, int]
    columns: List[str]
    dtypes: Dict[str, str]
    records: List[Dict[str, object]]

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame, system_id: int, source: str, limit: int = None):
        if df is None:
            df = pd.DataFrame()

        if limit is not None and df.shape[0] > limit:
            df = df.head(limit).copy()

        # JSON-safe: replace NaN/NaT/Inf with None
        def safe_df(d: pd.DataFrame) -> pd.DataFrame:
            d = d.replace([np.inf, -np.inf], np.nan)
            return d.where(pd.notna(d), None)

        sdf = safe_df(df)

        cols = [str(c) for c in sdf.columns]
        dtypes = {str(c): str(sdf[c].dtype) for c in sdf.columns}
        records = sdf.to_dict(orient="records")  # already sanitized to None

        return cls(
            system_id=system_id,
            source=source,
            shape=(len(records), len(cols)),
            columns=cols,
            dtypes=dtypes,
            records=records
        )

    def as_dict(self):
        return {
            "system_id": self.system_id,
            "source": self.source,
            "shape": list(self.shape),
            "columns": self.columns,
            "dtypes": self.dtypes,
            "records": self.records,
        }


class SystemSummary(BaseModel):
    """
    JSON shape used by the admin systems table.

    Notes:
        - time_added comes from the DB `updated_at` (insert/update time).
          If you later add a dedicated created_at, you can swap it in without
          changing the API contract.
    """
    system_id: int = Field(..., description="Unique numeric system identifier")
    time_added: str = Field(..., description="ISO-8601 timestamp of initial add or last update")
    last_scanned: Optional[str] = Field(None, description="ISO-8601 timestamp of last successful scan")
    has_csv: bool = Field(..., description="True if CSV path exists on disk and is a file")
    scan_policy: Optional[str] = None 
    
class AddSystemInput(BaseModel):
    """
    Payload for creating/upserting a system mapping.

    csv_path is optional; if omitted we record a canonical path under WORKING_DIR
    and you can upload later via the upload endpoint.
    """
    system_id: int
    csv_path: Optional[str] = None

class AddSystemBatchInput(BaseModel):
    """
    Used to add many systems to portfolio in bulk
    """
    items: List[AddSystemInput]


class ContinuousItem(BaseModel):
    """
    Response shape for a single monitored system in the Continuous Monitoring page.
    """
    system_id: int
    score: int                          # 0..100
    last_scanned: Optional[str] = None  # ISO-8601 or null
    monitored: bool                     # green/red light in UI

class Result(str, Enum):
    """
    Enumeration of possible outcomes for a compliance test.
    """
    PASS = "PASS"
    FAIL = "FAIL"
    CONCERN = "CONCERN"
    NA = "NA"


class TestResult(BaseModel):
    """
    Represents the outcome of a single compliance test.

    Attributes:
        test_number (int): Numeric identifier of the test (must be ≥ 1).
        name (str): Human-readable name of the test.
        result (Result): Final status (PASS, FAIL, CONCERN, NA).
        message (str): Descriptive message explaining the outcome.
    """
    test_number: int = Field(..., ge=1)
    name: str
    result: Result
    message: str


class ATOStatus(BaseModel):
    """
    Aggregates results across all executed tests and provides summary counts.
    """
    system_name: Optional[str] = None
    pass_count: int = 0
    fail_count: int = 0
    concern_count: int = 0
    na_count: int = 0
    results: List[TestResult] = Field(default_factory=list)

    def add(self, test_result: TestResult) -> None:
        """
        Add a new TestResult to the collection and update counters.

        Args:
            test_result (TestResult): The result object from an executed test.
        """
        self.results.append(test_result)

        if test_result.result == Result.PASS:
            self.pass_count += 1
        elif test_result.result == Result.FAIL:
            self.fail_count += 1
        elif test_result.result == Result.CONCERN:
            self.concern_count += 1
        elif test_result.result == Result.NA:
            self.na_count += 1

    def summary(self) -> str:
        """
        Produce a one-line summary of all test outcomes.

        Returns:
            str: Aggregated counts in human-readable format.
        """
        total = len(self.results)
        return (
            f"Total: {total} | "
            f"PASS: {self.pass_count} | "
            f"FAIL: {self.fail_count} | "
            f"CONCERN: {self.concern_count} | "
            f"N/A: {self.na_count}"
        )



class ChecklistArtifacts(BaseModel):
    """Bundle of outputs from a successful generate_checklist run."""
    job_id: str
    system_id: int
    excel_path: str
    csv_payload: DataFramePayload
    results_payload: Optional[DataFramePayload] = None
    status: Optional[ATOStatus] = None

    # Accept engine-provided ATOStatus from a different import path / identity.
    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v):
        if v is None:
            return None
        if isinstance(v, ATOStatus):
            return v
        # Try direct Pydantic validation of the foreign model/obj
        try:
            return ATOStatus.model_validate(v)
        except Exception:
            pass
        # Try model_dump() → validate
        try:
            data = v.model_dump()  # type: ignore[attr-defined]
            return ATOStatus.model_validate(data)
        except Exception:
            pass
        # Try dict-like coercion
        try:
            return ATOStatus.model_validate(dict(v))
        except Exception:
            pass
        raise TypeError(f"Cannot coerce status of type {type(v)} to ATOStatus")

    def as_dict(self) -> Dict[str, Any]:
        return _dump(self)

    def as_json(self) -> str:
        return _dump_json(self)

# =========================
# API / JSON SCHEMAS for scan policy stuff
# =========================



class ApiFrequencyEnum(str, enum.Enum):
    """API enum for accepted scan frequencies (request/response only)."""
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class ApiDayOfWeek(str, enum.Enum):
    """API enum for weekday names (UX-friendly values)."""
    MONDAY    = "Monday"
    TUESDAY   = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY  = "Thursday"
    FRIDAY    = "Friday"
    SATURDAY  = "Saturday"
    SUNDAY    = "Sunday"


class ScanPolicyCreate(BaseModel):
    """
    Create-policy payload.

    - frequency: daily/weekly/biweekly/monthly
    - time_of_day: "HH:MM[:SS]" (UTC)
    - day_of_week: required for weekly/monthly; optional for biweekly anchor
    - week_of_month: 1..5 (monthly, nth weekday)
    - anchor_epoch: optional origin for strict +14d cadence (biweekly)
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    frequency: ApiFrequencyEnum
    time_of_day: time
    day_of_week: Optional[ApiDayOfWeek] = None
    week_of_month: Optional[int] = Field(default=None, ge=1, le=5)
    anchor_epoch: Optional[int] = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class ScanPolicyUpdate(BaseModel):
    """
    Partial update for a policy.

    - Omitted fields are unchanged.
    - Send explicit null to clear optional fields.
    """
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    frequency: Optional[ApiFrequencyEnum] = None
    time_of_day: Optional[time] = None
    day_of_week: Optional[ApiDayOfWeek] = None
    week_of_month: Optional[int] = Field(default=None, ge=1, le=5)
    anchor_epoch: Optional[int] = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v


class SystemsBatch(BaseModel):
    """Batch enroll/remove systems by integer IDs."""
    model_config = ConfigDict(extra="forbid")
    system_ids: List[int] = Field(min_length=1)


class LastRunUpdate(BaseModel):
    """Explicitly set last_run_epoch (UTC epoch seconds)."""
    model_config = ConfigDict(extra="forbid")
    last_run_epoch: int = Field(ge=0)


class ScanPolicyOut(BaseModel):
    """
    Policy response object including enrolled systems.

    Notes:
      - time_of_day serialized as "HH:MM:SS"
      - systems: list of enrolled system_ids
    """
    id: int
    name: str
    frequency: ApiFrequencyEnum
    time_of_day: str
    day_of_week: Optional[ApiDayOfWeek] = None
    week_of_month: Optional[int] = None
    anchor_epoch: Optional[int] = None
    last_run_epoch: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    systems: List[int] = []




