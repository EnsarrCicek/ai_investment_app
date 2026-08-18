from fastapi import FastAPI

from app.api import analysis, assets, backtest, decisions, news, notifications, portfolio, risk

app = FastAPI(title="AI Yatirim Analiz Backend")

app.include_router(assets.router)
app.include_router(analysis.router)
app.include_router(decisions.router)
app.include_router(portfolio.router)
app.include_router(risk.router)
app.include_router(backtest.router)
app.include_router(news.router)
app.include_router(notifications.router)


@app.get("/health")
def health():
    return {"status": "ok"}
