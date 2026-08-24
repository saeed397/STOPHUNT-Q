"""
presentation/explain.py
Short, plain-language Persian explanations. No heavy jargon.
"""
from __future__ import annotations
from models.entry_sl_tp import SignalGroup
from engines.calibrator import AssetTimeframeProfile

def explain_group(group: SignalGroup, profile: AssetTimeframeProfile, asset: str) -> str:
    direction_fa = "خرید" if group.direction == "BUY" else "فروش"
    lines = []

    if group.mode == "STANDARD":
        lines.append(
            f"این سیگنال {direction_fa} بر اساس رفتار واقعی قبلی خود {asset} صادر شده. "
            f"قیمت یک سطح نقدینگی را شکار کرده، برگشته و حرکت قوی در جهت {direction_fa} نشان داده است."
        )
    else:
        lines.append(
            f"این یک سفارش معلق {direction_fa} است. هنوز فعال نشده. "
            f"وقتی قیمت به سطح مشخص‌شده برسد و حدضررهای دیگران را بزند، سفارش تو فعال می‌شود."
        )

    lines.append(
        f"سه ردیف حدسود و حدضرر با فاصله‌های متفاوت از سابقه نوسان و عمق شکارهای قبلی خود {asset} "
        f"محاسبه شده‌اند. ردیف ۴۰٪ نزدیک‌تر و محافظه‌کارتر، ردیف ۸۰٪ دورتر و جادارتر است."
    )

    lines.append(
        "اولویت همیشه با رفتار قبلی همین رمزارز بوده؛ نسبت ریسک به پاداش فقط وقتی استفاده شده "
        "که سطح نقدینگی واقعی مناسبی پیدا نشده باشد."
    )

    if profile.regime_shift_flag:
        word = "بیشتر" if profile.regime_shift_ratio > 1 else "کمتر"
        lines.append(
            f"⚠️ نوسان این رمزارز اخیراً به‌طور محسوسی {word} شده. با احتیاط بیشتری تصمیم بگیر."
        )

    return "\n\n".join(lines)
