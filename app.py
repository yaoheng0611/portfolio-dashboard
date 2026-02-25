import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import matplotlib.pyplot as plt

st.set_page_config(page_title="我的A股持仓看板", page_icon="📈", layout="wide")

# -----------------------------
# iOS Card CSS
# -----------------------------
IOS_CSS = """
<style>
/* overall spacing */
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

/* cards */
.ios-card {
  background: rgba(255,255,255,0.72);
  border: 1px solid rgba(120,120,120,0.18);
  box-shadow: 0 10px 30px rgba(0,0,0,0.06);
  border-radius: 18px;
  padding: 16px 16px;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  margin-bottom: 12px;
}

/* KPI value */
.kpi-title { font-size: 0.85rem; opacity: 0.72; margin-bottom: 6px; }
.kpi-value { font-size: 1.45rem; font-weight: 700; }
.kpi-sub   { font-size: 0.85rem; opacity: 0.72; margin-top: 2px; }

/* table tweaks */
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }

/* sidebar title */
.sidebar-title { font-weight: 700; font-size: 1.05rem; margin-bottom: 6px; }

/* chip */
.chip {
  display:inline-block; padding: 3px 10px; border-radius: 999px;
  border: 1px solid rgba(120,120,120,0.18);
  background: rgba(255,255,255,0.65);
  font-size: 0.82rem;
}
</style>
"""
st.markdown(IOS_CSS, unsafe_allow_html=True)

# -----------------------------
# Helpers
# -----------------------------
def load_holdings():
    with open("holdings.json", "r", encoding="utf-8") as f:
        return json.load(f)

def money(x: float) -> str:
    return f"¥{x:,.2f}"

def pct_from_ratio(r: float) -> str:
    # r=0.3 => "30.00%"
    return f"{r * 100:.2f}%"

def safe_float(x):
    try:
        return float(x)
    except:
        return None

# -----------------------------
# Quote Sources
# -----------------------------
def fetch_prices_tencent(codes):
    """
    Tencent free quote: returns last + prev_close
    """
    def to_symbol(code):
        code = str(code).zfill(6)
        return ("sh" + code) if code.startswith(("6", "9")) else ("sz" + code)

    symbols = [to_symbol(c) for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)

    r = requests.get(url, timeout=8)
    r.encoding = "gbk"
    text = r.text

    out = {}
    # v_sh600759="51~洲际油气~600759~3.21~3.20~..."
    for line in text.split(";"):
        m = re.search(r'v_(sh|sz)(\d{6})="([^"]*)"', line)
        if not m:
            continue
        code = m.group(2)
        payload = m.group(3).split("~")
        if len(payload) > 4:
            last = safe_float(payload[3])
            prev_close = safe_float(payload[4])
            if last and last > 0:
                out[code] = {"last": last, "prev_close": prev_close}
    return out

def fetch_prices_xueqiu(codes):
    """
    Xueqiu quote (often blocked on cloud). We'll try, but must fallback.
    """
    out = {}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://xueqiu.com/",
    }

    def to_xq_symbol(code):
        code = str(code).zfill(6)
        return ("SH" + code) if code.startswith(("6", "9")) else ("SZ" + code)

    for code in codes:
        symbol = to_xq_symbol(code)
        url = f"https://stock.xueqiu.com/v5/stock/quote.json?symbol={symbol}&extend=detail"
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            continue
        j = r.json()
        q = (j or {}).get("data", {}).get("quote", {})
        last = safe_float(q.get("current"))
        prev_close = safe_float(q.get("last_close"))
        if last and last > 0:
            out[code] = {"last": last, "prev_close": prev_close}
    return out

def fetch_prices_akshare(codes):
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    df = df[["代码", "最新价"]].copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    out = {}
    for c in codes:
        row = df.loc[df["代码"] == str(c).zfill(6)]
        if not row.empty:
            out[str(c).zfill(6)] = {"last": float(row.iloc[0]["最新价"]), "prev_close": None}
    return out

def fetch_prices(codes, preferred: str):
    """
    preferred:
      - "雪球优先（失败自动切换）"
      - "腾讯（稳定）"
      - "akshare(东方财富)"
    """
    err = []
    used = None
    quotes = {}

    if preferred.startswith("雪球"):
        # try xueqiu -> tencent
        try:
            quotes = fetch_prices_xueqiu(codes)
            if quotes:
                used = "雪球"
            else:
                err.append("雪球未取到数据（云端常见）")
        except Exception as e:
            err.append(f"雪球失败：{e}")

        if not quotes:
            try:
                quotes = fetch_prices_tencent(codes)
                used = "腾讯(备用)"
            except Exception as e2:
                err.append(f"腾讯也失败：{e2}")

    elif preferred.startswith("腾讯"):
        try:
            quotes = fetch_prices_tencent(codes)
            used = "腾讯"
        except Exception as e:
            err.append(f"腾讯失败：{e}")

    else:
        # akshare
        try:
            quotes = fetch_prices_akshare(codes)
            used = "akshare(东方财富)"
        except Exception as e:
            err.append(f"akshare失败：{e}")
            # fallback to tencent
            try:
                quotes = fetch_prices_tencent(codes)
                used = "腾讯(备用)"
            except Exception as e2:
                err.append(f"腾讯也失败：{e2}")

    return quotes, used, ("；".join(err) if err else None)

# -----------------------------
# Load portfolio
# -----------------------------
data = load_holdings()
holdings = data["holdings"]
codes = [h["code"] for h in holdings]

# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.markdown('<div class="sidebar-title">⚙️ 控制台</div>', unsafe_allow_html=True)

    total_assets = st.number_input("总资产（RMB）", value=float(data.get("total_assets_rmb", 0.0)), step=1000.0)
    # 你提到“仓位比希望是扇形图”——这里保留仓位%仅作为展示/参考（不用于计算现金）
    position_ratio = st.slider("你自报仓位（%）", 0.0, 100.0, float(data.get("position_ratio", 0.0) * 100), 0.1) / 100.0

    preferred = st.selectbox(
        "行情源偏好",
        ["雪球优先（失败自动切换）", "腾讯（稳定）", "akshare(东方财富)"],
        index=0
    )

    if st.button("🔄 刷新"):
        st.rerun()

    st.divider()
    st.markdown("📰 **新闻快捷入口**（点开即搜）")
    for h in holdings:
        code = h["code"]
        name = h["name"]
        st.link_button(
            f"{name}（{code}）",
            f"https://www.google.com/search?q={name}+{code}+A%E8%82%A1+%E6%96%B0%E9%97%BB"
        )

# -----------------------------
# Fetch quotes
# -----------------------------
quotes, used_source, err = fetch_prices(codes, preferred)

# -----------------------------
# Build table with Today PnL + Total PnL
# -----------------------------
rows = []
for h in holdings:
    code = str(h["code"]).zfill(6)
    name = h["name"]
    shares = float(h["shares"])
    cost = float(h["cost"])

    q = quotes.get(code, {})
    last = q.get("last")
    prev_close = q.get("prev_close")

    mv = (last * shares) if (last is not None) else None
    total_pnl = ((last - cost) * shares) if (last is not None) else None
    total_return = ((last / cost - 1.0) if (last is not None and cost > 0) else None)

    today_pnl = ((last - prev_close) * shares) if (last is not None and prev_close is not None) else None
    today_return = ((last / prev_close - 1.0) if (last is not None and prev_close is not None and prev_close > 0) else None)

    rows.append({
        "代码": code,
        "名称": name,
        "持股(股)": int(shares),
        "成本价": cost,
        "昨收": prev_close,
        "现价": last,
        "持仓市值": mv,
        "今日盈亏": today_pnl,
        "今日%": today_return,
        "总盈亏": total_pnl,
        "总收益率": total_return,
    })

df = pd.DataFrame(rows)

mv_sum = float(df["持仓市值"].dropna().sum()) if "持仓市值" in df else 0.0
today_pnl_sum = float(df["今日盈亏"].dropna().sum()) if "今日盈亏" in df else 0.0
total_pnl_sum = float(df["总盈亏"].dropna().sum()) if "总盈亏" in df else 0.0

# 总投入成本（用于整体收益率）
cost_basis = 0.0
for h in holdings:
    cost_basis += float(h["cost"]) * float(h["shares"])
overall_return = (total_pnl_sum / cost_basis) if cost_basis > 0 else 0.0

cash_est = max(total_assets - mv_sum, 0.0)

# -----------------------------
# UI
# -----------------------------
st.title("📈 我的A股持仓看板")
subline = f'行情源：<span class="chip">{used_source or "—"}</span>　仓位(自报)：<span class="chip">{pct_from_ratio(position_ratio)}</span>'
st.markdown(subline, unsafe_allow_html=True)

if err:
    st.warning("行情获取部分不稳定（云端常见），已自动兜底。\n\n" + err)

# KPI cards
c1, c2, c3, c4, c5 = st.columns(5)

def kpi(card_col, title, value, sub=""):
    with card_col:
        st.markdown(
            f"""
            <div class="ios-card">
              <div class="kpi-title">{title}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

kpi(c1, "总资产", money(total_assets), "")
kpi(c2, "估算现金", money(cash_est), "总资产 - 持仓市值")
kpi(c3, "持仓市值", money(mv_sum), "")
kpi(c4, "今日盈亏", money(today_pnl_sum), "")
kpi(c5, "总盈亏 / 总收益率", f"{money(total_pnl_sum)}", f"{pct_from_ratio(overall_return)}")

# Table styling
st.subheader("📌 持仓明细")

def fmt_money(x):
    return "" if (x is None or pd.isna(x)) else f"{float(x):,.2f}"

def fmt_price(x):
    return "" if (x is None or pd.isna(x)) else f"{float(x):.3f}"

def fmt_pct(x):
    return "" if (x is None or pd.isna(x)) else f"{float(x)*100:.2f}%"

def color_posneg(v):
    if v is None or pd.isna(v):
        return ""
    return "color:#16a34a; font-weight:700;" if float(v) > 0 else ("color:#dc2626; font-weight:700;" if float(v) < 0 else "")

show = df.copy()
styled = show.style \
    .applymap(color_posneg, subset=["今日盈亏", "总盈亏"]) \
    .format({
        "成本价": fmt_price,
        "昨收": fmt_price,
        "现价": fmt_price,
        "持仓市值": fmt_money,
        "今日盈亏": fmt_money,
        "今日%": fmt_pct,
        "总盈亏": fmt_money,
        "总收益率": fmt_pct,
    })

st.dataframe(styled, use_container_width=True, height=260)

# Charts
st.subheader("📊 结构视图")

left, right = st.columns(2)

chart_df = df.dropna(subset=["持仓市值"]).copy()
if not chart_df.empty:
    with left:
        st.markdown('<div class="ios-card">', unsafe_allow_html=True)
        st.caption("仓位占比（扇形图 / 按持仓市值）")
        fig = plt.figure()
        plt.pie(
            chart_df["持仓市值"],
            labels=chart_df["名称"],
            autopct="%1.1f%%",
            startangle=90
        )
        plt.axis("equal")
        st.pyplot(fig)
        st.markdown("</div>", unsafe_allow_html=True)

    with right:
        st.markdown('<div class="ios-card">', unsafe_allow_html=True)
        st.caption("盈亏分布（今日 vs 总）")
        bar_df = chart_df.set_index("名称")[["今日盈亏", "总盈亏"]]
        st.bar_chart(bar_df)
        st.markdown("</div>", unsafe_allow_html=True)

st.caption("更新时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
