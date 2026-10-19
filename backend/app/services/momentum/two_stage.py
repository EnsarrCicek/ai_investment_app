"""İki aşamalı erken momentum dedektörü (Round 2 araştırması) — SAF; tarayıcıya/API'ye BAĞLI DEĞİL.

Aşama A — EARLY WATCH: yüksek duyarlılık, kontrollü yanlış alarm. Round 1 kanıt grupları (fiyat + katılım/yapı)
VEYA (açıksa) ivme / gap-devam / dönüş tetikleyicileri; ardından (açıksa) benchmark-göreli ve kesitsel kapılar.
Aşama B — CONFIRMED STRONG: Round 1 STRONG kuralı + (açıksa) göreli güç, hacim, VWAP yapısı ve kırılım kalitesi.

Durum geçişi (seans içi): NONE → WATCH → STRONG. STRONG yalnız aynı seansta daha önce WATCH doğrulanmışsa verilir;
doğrudan STRONG yalnız açık "aşırı" kuralıyla (`allow_direct_strong`). Bağlam verisi (benchmark/kesitsel) yoksa ilgili
kapı UYGULANMAZ ve gerekçe olarak işaretlenir (uydurma değer yok); varlığın kendi kanıtı eksikse kanıt sayılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from app.models import momentum_alert as ma
from app.services.momentum.cross_section import REGIME_SHOCK

_RANK = {ma.LEVEL_NONE: 0, ma.LEVEL_WATCH: 1, ma.LEVEL_STRONG: 2}


class TwoStageConfig(BaseModel):
    """Eşikler σ birimlidir (ölçekten bağımsız) ve sonuç görülmeden sabitlenmiştir (research defaults)."""

    model_config = ConfigDict(frozen=True)

    watch_k: int = 2
    watch_n: int = 3
    strong_k: int = 3
    strong_n: int = 3
    # A: ivme tetikleyicisi
    use_accel: bool = False
    accel_min: float = 0.5  # (15 dk eğim − önceki 60 dk eğim) σ/bar
    accel_pos_min: int = 2  # son 3 değerlendirmenin ≥2'sinde ivme > 0 (tek bar sıçraması değil)
    accel_ret_z3_min: float = 1.5
    # A: kapılar
    use_rel: bool = False
    rel_z3_min: float = 1.0
    use_xs: bool = False
    xs_min: float = 0.90
    use_regime: bool = False
    regime_xs_min: float = 0.95
    use_volacc: bool = False
    volacc_relvol_min: float = 1.5
    # A: ek tetikleyiciler
    use_gap: bool = False
    gap_min_pct: float = 1.0
    gap_follow_z_min: float = 1.0
    gap_min_bars: int = 3
    use_reversal: bool = False
    reversal_min_drawdown_pct: float = 15.0
    reversal_ret_z3_min: float = 1.0
    use_locked_fallback: bool = False
    locked_price_z_min: float = 2.0
    # B: doğrulama
    strong_confirm: bool = False
    strong_rel_z6_min: float = 1.5
    strong_relvol_min: float = 1.5
    strong_structure_quality: bool = False
    strong_vwap_time_above: float = 0.5
    strong_breakout_atr: float = 0.5
    strong_breakout_age: int = 2
    allow_direct_strong: bool = True
    extreme_price_z: float = 6.0
    extreme_relvol: float = 5.0


def _ge(x, thr) -> bool:
    return x is not None and x >= thr


def raw_watch(f: dict, cfg: TwoStageConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    triggers = []
    if f.get("r1_level") in (ma.LEVEL_WATCH, ma.LEVEL_STRONG):
        triggers.append("R1_GROUPS")
    if cfg.use_accel and _ge(f.get("accel"), cfg.accel_min) and (f.get("accel_pos_3") or 0) >= cfg.accel_pos_min \
            and _ge(f.get("ret_z_3"), cfg.accel_ret_z3_min) and (f.get("session_ret_pct") or 0) > 0:
        triggers.append("ACCELERATION")
    if cfg.use_gap and _ge(f.get("gap_pct"), cfg.gap_min_pct) and _ge(f.get("gap_follow_z"), cfg.gap_follow_z_min) \
            and (f.get("n_bars") or 0) >= cfg.gap_min_bars and (f.get("vwap_dist_pct") or 0) > 0:
        triggers.append("GAP_FOLLOW_THROUGH")
    if cfg.use_reversal and _ge(f.get("prior_drawdown_pct"), cfg.reversal_min_drawdown_pct) \
            and f.get("higher_low") is True and f.get("reclaim_prev_high") is True \
            and _ge(f.get("ret_z_3"), cfg.reversal_ret_z3_min):
        triggers.append("REVERSAL_QUALITY")
    if cfg.use_locked_fallback and f.get("r1_price_impulse") is None and f.get("recent_locked_regime") \
            and _ge(f.get("price_z_ext"), cfg.locked_price_z_min) and (f.get("session_ret_pct") or 0) > 0:
        triggers.append("LOCKED_REGIME_LOW_CONFIDENCE")
    if not triggers:
        return False, reasons
    reasons.extend(triggers)
    if cfg.use_rel:
        rel = f.get("rel_ret_z_3")
        if rel is None:
            reasons.append("BENCHMARK_UNAVAILABLE")
        elif rel < cfg.rel_z3_min:
            return False, reasons + ["REL_GATE_FAIL"]
    if cfg.use_xs:
        xs = f.get("xs_ret")
        thr = cfg.regime_xs_min if (cfg.use_regime and f.get("regime") == REGIME_SHOCK) else cfg.xs_min
        if xs is None:
            reasons.append("CROSS_SECTION_UNAVAILABLE")
        elif xs < thr:
            return False, reasons + ["XS_GATE_FAIL"]
    if cfg.use_volacc and not (_ge(f.get("relvol_3"), cfg.volacc_relvol_min)
                               or (f.get("vol_accel") is not None and f["vol_accel"] > 0)):
        return False, reasons + ["VOLUME_GATE_FAIL"]
    return True, reasons


def raw_strong(f: dict, cfg: TwoStageConfig) -> tuple[bool, bool]:
    """(STRONG kanıtı, aşırı durum)."""
    extreme = (_ge(f.get("price_z_ext"), cfg.extreme_price_z) and _ge(f.get("relvol_3"), cfg.extreme_relvol)
               and _ge(f.get("breakout_dist_atr"), 0.0) and f.get("r1_level") == ma.LEVEL_STRONG)
    if f.get("r1_level") != ma.LEVEL_STRONG:
        return False, False
    if cfg.strong_confirm:
        rel = f.get("rel_ret_z_6")
        if (rel is not None and rel < cfg.strong_rel_z6_min) or not _ge(f.get("relvol_3"), cfg.strong_relvol_min):
            return False, extreme
    if cfg.strong_structure_quality:
        vwap_ok = _ge(f.get("vwap_time_above"), cfg.strong_vwap_time_above) and (f.get("vwap_slope") or 0) > 0
        bo_ok = _ge(f.get("breakout_dist_atr"), cfg.strong_breakout_atr) or \
            (f.get("breakout_age") or 0) >= cfg.strong_breakout_age
        if not (vwap_ok and bo_ok):
            return False, extreme
    return True, extreme


@dataclass
class SessionTracker:
    """Tek (varlık, seans) için ardışık değerlendirmeler (5 dk arayla, eskiden yeniye)."""

    cfg: TwoStageConfig
    watch_hist: list[bool] = field(default_factory=list)
    strong_hist: list[bool] = field(default_factory=list)
    watch_confirmed: bool = False

    def step(self, f: dict) -> tuple[str, list[str]]:
        cfg = self.cfg
        w, reasons = raw_watch(f, cfg)
        s, extreme = raw_strong(f, cfg)
        s = s and w  # STRONG kanıtı WATCH kapılarını da geçmeli
        self.watch_hist.append(w)
        self.strong_hist.append(s)
        w_ok = w and sum(self.watch_hist[-cfg.watch_n:]) >= cfg.watch_k
        s_ok = s and sum(self.strong_hist[-cfg.strong_n:]) >= cfg.strong_k
        level = ma.LEVEL_NONE
        if s_ok and (self.watch_confirmed or (cfg.allow_direct_strong and extreme)):
            level = ma.LEVEL_STRONG
            if not self.watch_confirmed:
                reasons = reasons + ["DIRECT_STRONG_EXTREME"]
        elif w_ok or s_ok:
            level = ma.LEVEL_WATCH
            if s_ok:
                reasons = reasons + ["STRONG_DEFERRED_UNTIL_WATCH"]
        if _RANK[level] >= 1:
            self.watch_confirmed = True
        return level, reasons
