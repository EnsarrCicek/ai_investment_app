from fastapi import APIRouter, Header, HTTPException

from app.core.config import DAILY_JOB_SECRET
from app.services.jobs.daily_analysis import run_daily_analysis

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/daily-analysis")
def daily_analysis(x_job_secret: str | None = Header(default=None)):
    """AŞAMA 70 — Google Cloud Scheduler'ın günde bir kez çağırdığı uç nokta
    (bkz. `app/services/jobs/daily_analysis.py` docstring'i). `DAILY_JOB_SECRET`
    ayarlı değilse ya da eşleşmiyorsa 403 döner — herkese açık bir adreste
    gerçek OpenAI maliyeti oluşturan bir işlemi kimliği doğrulanmamış hiç
    kimse tetikleyemez.
    """
    if not DAILY_JOB_SECRET or x_job_secret != DAILY_JOB_SECRET:
        raise HTTPException(status_code=403, detail="Geçersiz veya eksik job secret")
    return run_daily_analysis()
