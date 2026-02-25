import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import altair as alt

st.set_page_config(page_title="我的A股持仓看板", page_icon="📈", layout="wide")

# -----------------------------
# iOS Card CSS
# -----------------------------
IOS_CSS = """
<style>
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
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
.kpi-title { font-size: 0.85rem; opacity: 0.72; margin-bottom: 6px; }
.kpi-value { font-size: 1.45rem; font-weight: 700; }
.kpi-sub   { font-size: 0.85rem; opacity: 0.72; margin-top: 2px; }
[data-testid="stDataFrame"] { border-radius: 14px; overflow: hidden; }
.sidebar-title { font-weight: 700; font-size: 1.05rem; margin-bottom: 6px; }
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
    def to_symbol(code):
        code = str(code).zfill(6)
        return ("sh" + code) if code.startswith(("6", "9")) else ("sz" + code)

    symbols = [to_symbol(c) for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)

    r = requests.get(url, timeout=8)
    r.encoding = "gbk"
    text = r.text

    out = {}
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
    err = []
    used = None
    quotes = {}

    if preferred.startswith("雪球"):
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
        try:
            quotes = fetch_prices_akshare(codes)
            used = "akshare(东方财富)"
        except Exception as e:
            err.append(f"akshare失败：{e}")
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
    position_ratio = st.slider("你自报仓位（%）", 0.0, 100.0, float(data.get("position_ratio", 0.0) * 100), 0.1) / 100.0

    preferred = st.selectbox(
        "行情源偏好",
        ["雪球优先（失败自动切换）", "腾讯（稳定）", "akshare(东方财富)"],
        index=0
    )

    # 右侧图：选择展示“今日”还是“总”
    pnl_mode = st.radio("右侧盈亏图展示", ["今日盈亏（更直观）", "总盈亏"], index=0)

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
cost_basis = 0.0
for h in holdings:
    code = str(h["code"]).zfill(6)
    name = h["name"]
    shares = float(h["shares"])
    cost = float(h["cost"])
    cost_basis += cost * shares

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

styled = df.style \
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

# -----------------------------
# Charts (Altair to avoid Chinese font issues)
# -----------------------------
st.subheader("📊 结构视图")
left, right = st.columns(2)

chart_df = df.dropna(subset=["持仓市值"]).copy()

# 1) Pie chart with cash slice
pie_rows = []
if not chart_df.empty:
    for _, r in chart_df.iterrows():
        pie_rows.append({"名称": r["名称"], "金额": float(r["持仓市值"]), "类别": "持仓"})
# add cash
pie_rows.append({"名称": "现金/未用资金", "金额": float(max(cash_est, 0.0)), "类别": "现金"})

pie_df = pd.DataFrame(pie_rows)

with left:
    st.markdown('<div class="ios-card">', unsafe_allow_html=True)
    st.caption("仓位占比（扇形图 / 按金额）")

    pie_chart = alt.Chart(pie_df).mark_arc(outerRadius=120).encode(
        theta=alt.Theta(field="金额", type="quantitative"),
        color=alt.Color(
            field="名称",
            type="nominal",
            scale=alt.Scale(domain=list(pie_df["名称"]), range=None),
            legend=alt.Legend(orient="bottom")
        ),
        tooltip=["名称", alt.Tooltip("金额:Q", format=",.2f")]
    ).properties(height=340)

    # 将“现金/未用资金”固定为灰色：用 condition 做二次覆盖
    pie_chart = pie_chart.encode(
        color=alt.Color(
            "名称:N",
            scale=alt.Scale(
                domain=list(pie_df["名称"]),
                range=["#9CA3AF" if n == "现金/未用资金" else None for n in pie_df["名称"]]
            ),
            legend=alt.Legend(orient="bottom")
        )
    )

    st.altair_chart(pie_chart, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# 2) Right chart: single series + horizontal labels
with right:
    st.markdown('<div class="ios-card">', unsafe_allow_html=True)

    if pnl_mode.startswith("今日"):
        st.caption("盈亏分布（今日盈亏）")
        d = chart_df[["名称", "今日盈亏"]].dropna().copy()
        d.rename(columns={"今日盈亏": "盈亏"}, inplace=True)
    else:
        st.caption("盈亏分布（总盈亏）")
        d = chart_df[["名称", "总盈亏"]].dropna().copy()
        d.rename(columns={"总盈亏": "盈亏"}, inplace=True)

    if d.empty:
        st.info("暂无可展示数据（行情未取到或无昨收数据）")
    else:
        bar = alt.Chart(d).mark_bar().encode(
            x=alt.X("名称:N", sort="-y", axis=alt.Axis(labelAngle=0, title=None)),  # 横向文字
            y=alt.Y("盈亏:Q", axis=alt.Axis(title=None)),
            tooltip=["名称", alt.Tooltip("盈亏:Q", format=",.2f")]
        ).properties(height=340)

        st.altair_chart(bar, use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

st.caption("更新时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
