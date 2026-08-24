"""
app/streamlit_app.py
Exact UI matching the user's required layout.
Run: streamlit run app/streamlit_app.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from config import TIMEFRAME_ORDER, HIGHER_TIMEFRAME_MAP, RR_OPTIONS, DEFAULT_RR
from data.providers import MultiProviderOHLC, CoinGeckoProvider, ProviderError
from engines.stophunt_engine import run_signal_engine, SignalEngineError
from engines.calibrator import CalibrationError
from presentation.explain import explain_group

st.set_page_config(page_title="Liquidity Stop-Hunt System", layout="wide", page_icon="🎯")

# Custom CSS for clean signal boxes
st.markdown("""
<style>
.signal-box {
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 12px;
    background: rgba(255,255,255,0.02);
}
.signal-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 12px;
}
.price-row {
    display: flex;
    justify-content: space-between;
    font-size: 1.05rem;
    margin: 6px 0;
    padding: 4px 0;
    border-bottom: 1px solid rgba(128,128,128,0.15);
}
.price-label { opacity: 0.7; min-width: 90px; }
.price-entry { color: #d4a017; font-weight: 700; }
.price-tp { color: #1f9d55; font-weight: 700; }
.price-sl { color: #e0303d; font-weight: 700; }
.risk-badge {
    background: rgba(100,100,100,0.2);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.85rem;
}
.level-col {
    text-align: center;
    padding: 8px;
}
.header-price {
    font-size: 1.4rem;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=3600, show_spinner="در حال دریافت ۵۰۰ رمزارز برتر از CoinGecko...")
def load_asset_universe():
    provider = CoinGeckoProvider()
    return provider.get_top_assets()

def render_levels(medium, strong, is_buy: bool):
    label_med = "۳ مقاومت متوسط" if is_buy else "۳ حمایت متوسط"
    label_str = "۳ مقاومت قوی" if is_buy else "۳ حمایت قوی"
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**{label_med}**")
        if medium:
            for lv in medium:
                st.write(f"`{lv.price:.4f}`")
        else:
            st.caption("سطح مناسبی یافت نشد")
    with col2:
        st.markdown(f"**{label_str}**")
        if strong:
            for lv in strong:
                st.write(f"`{lv.price:.4f}`")
        else:
            st.caption("سطح مناسبی یافت نشد")

def render_signal_group(title: str, group, profile, asset: str):
    if group is None or not group.rows:
        st.caption("در حال حاضر سیگنال معتبری برای این گروه وجود ندارد.")
        return

    st.markdown(f"<div class='signal-box'><div class='signal-title'>{title}</div>", unsafe_allow_html=True)

    # Header row
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
    c1.markdown("**حد سود**")
    c2.markdown("**قیمت سفارش**")
    c3.markdown("**حد ضرر**")
    c4.markdown("**ریسک**")

    for row in group.rows:
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        c1.markdown(f"<span class='price-tp'>{row.take_profit:.4f}</span>", unsafe_allow_html=True)
        c2.markdown(f"<span class='price-entry'>{row.entry_price:.4f}</span>", unsafe_allow_html=True)
        c3.markdown(f"<span class='price-sl'>{row.stop_loss:.4f}</span>", unsafe_allow_html=True)
        c4.markdown(f"<span class='risk-badge'>{row.risk_label}</span>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("ℹ️ توضیحات"):
        st.write(explain_group(group, profile, asset))

def main():
    st.title("سامانه هوشمند تحلیل نقدینگی و سفارش‌گذاری (Stop Hunt)")
    st.caption("سیگنال کم ولی معتبر • اولویت با سابقه اختصاصی هر رمزارز")

    with st.sidebar:
        st.header("⚙️ تنظیمات")
        try:
            universe = load_asset_universe()
        except ProviderError as e:
            st.error(f"عدم دسترسی به فهرست رمزارزها: {e}")
            st.stop()

        asset_labels = [f"{a['symbol']} — {a['name']}" for a in universe]
        asset_choice = st.selectbox("انتخاب رمزارز", asset_labels, index=0)
        chosen = universe[asset_labels.index(asset_choice)]
        asset_symbol = chosen["symbol"]
        coingecko_id = chosen["id"]

        quote = st.selectbox("ارز پایه", ["USD", "USDT"], index=0)
        timeframe = st.selectbox("تایم‌فریم اصلی", TIMEFRAME_ORDER, index=TIMEFRAME_ORDER.index("4h"))
        higher_tf = HIGHER_TIMEFRAME_MAP[timeframe]
        st.text_input("تایم‌فریم بالاتر (auto)", value=higher_tf, disabled=True)

        rr_label = st.selectbox("نسبت ریسک/پاداش (fallback)", RR_OPTIONS, index=RR_OPTIONS.index(DEFAULT_RR))
        rr_target = float(rr_label.split(":")[1])

        direction = st.radio("جهت سیگنال", ["Buy", "Sell", "Both"], horizontal=True)

        with st.expander("داده پیشرفته"):
            lookback = st.slider("تعداد کندل تاریخی", 400, 2000, 900, step=100)
            calib_window = st.slider("پنجره کالیبراسیون", 200, 800, 350, step=50)

        confirm = st.button("✅ تایید و اجرا", type="primary", use_container_width=True)

    if not confirm:
        st.info("تنظیمات را انتخاب و روی «تایید و اجرا» کلیک کنید.")
        return

    provider = MultiProviderOHLC()
    with st.spinner("در حال دریافت داده و اجرای موتور تحلیل سخت‌گیرانه..."):
        try:
            result = run_signal_engine(
                asset=asset_symbol,
                coingecko_id=coingecko_id,
                quote=quote,
                timeframe=timeframe,
                direction=direction,
                rr_target=rr_target,
                provider=provider,
                lookback=lookback,
                calibration_window=calib_window,
            )
        except (SignalEngineError, CalibrationError, ProviderError) as e:
            st.error(f"⚠️ {e}")
            st.stop()

    # ===== HEADER =====
    dir_color = "🟢" if result.direction in ("BUY", "BOTH") else "🔴"
    st.markdown(
        f"### {result.asset}/{quote} &nbsp;&nbsp; "
        f"<span class='header-price'>{result.current_price:.4f}</span> &nbsp;&nbsp; "
        f"{dir_color} {result.direction} &nbsp;&nbsp; {result.timeframe}",
        unsafe_allow_html=True
    )
    st.caption(f"منبع داده: {result.data_source} | کندل‌های معتبر: {result.data_quality.total_candles}")

    # ===== LEVELS =====
    is_buy_view = result.direction != "SELL"
    render_levels(result.medium_levels, result.strong_levels, is_buy=is_buy_view)

    st.divider()

    # ===== TWO GROUPS =====
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("قیمت‌گذاری نسبت به قیمت کنونی")
        render_signal_group(
            "📍 سیگنال لحظه‌ای (Standard)",
            result.standard_group,
            result.profile,
            result.asset,
        )

    with col2:
        st.subheader("قیمت‌گذاری براساس StopHunt")
        render_signal_group(
            "🎯 سفارش معلق (Stop-Hunt Trigger)",
            result.stophunt_group,
            result.profile,
            result.asset,
        )

    if result.notes:
        with st.expander("یادداشت‌های موتور"):
            for n in result.notes:
                st.write("• " + n)

if __name__ == "__main__":
    main()
