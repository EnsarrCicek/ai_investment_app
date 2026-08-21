from fastapi import FastAPI

from app.api import (
    analysis,
    analysts,
    assets,
    backtest,
    decisions,
    funds,
    ipo,
    market_data,
    news,
    news_analysis,
    notifications,
    portfolio,
    risk,
    usage,
)

app = FastAPI(title="AI Yatirim Analiz Backend")

app.include_router(assets.router)
app.include_router(analysis.router)
app.include_router(decisions.router)
app.include_router(portfolio.router)
app.include_router(risk.router)
app.include_router(backtest.router)
app.include_router(news.router)
app.include_router(news_analysis.router)
app.include_router(notifications.router)
app.include_router(usage.router)
app.include_router(market_data.router)
app.include_router(funds.router)
app.include_router(analysts.router)
app.include_router(ipo.router)


@app.get("/health")
def health():
    return {"status": "ok"}
