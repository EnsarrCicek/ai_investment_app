import pytest
from fastapi import HTTPException

from app.api import jobs as jobs_module


def test_rejects_request_without_secret_configured(monkeypatch):
    monkeypatch.setattr(jobs_module, "DAILY_JOB_SECRET", None)

    with pytest.raises(HTTPException) as exc_info:
        jobs_module.daily_analysis(x_job_secret="anything")

    assert exc_info.value.status_code == 403


def test_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(jobs_module, "DAILY_JOB_SECRET", "correct-secret")

    with pytest.raises(HTTPException) as exc_info:
        jobs_module.daily_analysis(x_job_secret="wrong-secret")

    assert exc_info.value.status_code == 403


def test_rejects_missing_header(monkeypatch):
    monkeypatch.setattr(jobs_module, "DAILY_JOB_SECRET", "correct-secret")

    with pytest.raises(HTTPException) as exc_info:
        jobs_module.daily_analysis(x_job_secret=None)

    assert exc_info.value.status_code == 403


def test_runs_job_when_secret_matches(monkeypatch):
    monkeypatch.setattr(jobs_module, "DAILY_JOB_SECRET", "correct-secret")
    monkeypatch.setattr(jobs_module, "run_daily_analysis", lambda: {"processed": 3})

    result = jobs_module.daily_analysis(x_job_secret="correct-secret")

    assert result == {"processed": 3}
