import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import altair as alt

st.set_page_config(page_title="我的A股持仓看板", page_icon="📈", layout="wide")

# =============================
# iOS 风格
# =============================
st.markdown("""
<style>
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
.ios-card {
  background: rgba(255,255,255,0.75);
  border: 1px solid rgba(120,120,120,0.15);
  box-shadow: 0 8px 25px rgba(0,0,0,0.06);
  border-radius: 18px;
  padding: 16px;
  margin-bottom: 14px;
}
.kpi-title { font-size: 0.85rem; opacity: 0.7; }
.kpi-value { font-size: 1.4rem; font-weight: 700; }
.kpi-sub { font-size: 0.8rem; opacity: 0.6; }
</style>
""", unsafe_allow_html=True)

# =============================
# 工具函数
# =============================
def load_holdings():
    with open("holdings.json", "r", encoding="utf-8") as f:
        return json.load(f)

def money(x):
    return f"¥{x:,.2f}"

def pct(x):
    return f"{x*100:.2f}%"

def safe_float(x):
    try:
        return float(x)
    except:
        return None

# =============================
# 腾讯行情（稳定）
# =============================
def fetch_prices(codes):
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

# =============================
# 读取数据
# =============================
data = load_holdings()
holdings = data["holdings"]
total_assets = float(data.get("total_assets_rmb", 0))
codes = [h["code"] for h in holdings]

quotes = fetch_prices(codes)

rows = []
cost_basis = 0

for h in holdings:
    code = str(h["code"]).zfill(6)
    name = h["name"]
    shares = float(h["shares"])
    cost = float(h["cost"])
    cost_basis += cost * shares

    q = quotes.get(code, {})
    last = q.get("last")
    prev = q.get("prev_close")

    mv = last * shares if last else None
    total_pnl = (last - cost) * shares if last else None
    total_return = (last / cost - 1) if last else None

    today_pnl = (last - prev) * shares if last and prev else None

    rows.append({
        "名称": name,
        "持仓市值": mv,
        "今日盈亏": today_pnl,
        "总盈亏": total_pnl,
    })

df = pd.DataFrame(rows)

mv_sum = df["持仓市值"].sum()
today_sum = df["今日盈亏"].sum()
total_sum = df["总盈亏"].sum()
overall_return = total_sum / cost_basis if cost_basis else 0
cash = max(total_assets - mv_sum, 0)

# =============================
# 顶部KPI
# =============================
c1, c2, c3, c4, c5 = st.columns(5)

def card(col, title, value, sub=""):
    with col:
        st.markdown(f"""
        <div class="ios-card">
            <div class="kpi-title">{title}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-sub">{sub}</div>
        </div>
        """, unsafe_allow_html=True)

card(c1, "总资产", money(total_assets))
card(c2, "现金", money(cash))
card(c3, "持仓市值", money(mv_sum))
card(c4, "今日盈亏", money(today_sum))
card(c5, "总盈亏", money(total_sum), pct(overall_return))

# =============================
# 饼图（含现金 灰色）
# =============================
st.subheader("📊 仓位结构")

pie_df = df[["名称", "持仓市值"]].dropna().copy()
pie_df = pie_df.rename(columns={"持仓市值": "金额"})

pie_df = pd.concat([
    pie_df,
    pd.DataFrame([{"名称": "现金/未用资金", "金额": cash}])
])

pie = alt.Chart(pie_df).mark_arc(outerRadius=130).encode(
    theta="金额:Q",
    color=alt.condition(
        alt.datum["名称"] == "现金/未用资金",
        alt.value("#9CA3AF"),
        alt.Color("名称:N")
    ),
    tooltip=["名称", alt.Tooltip("金额:Q", format=",.2f")]
).properties(height=380)

st.altair_chart(pie, use_container_width=True)

# =============================
# 右侧柱状（单色 横向）
# =============================
st.subheader("📈 盈亏分布")

mode = st.radio("展示", ["今日盈亏", "总盈亏"], horizontal=True)

if mode == "今日盈亏":
    chart_df = df[["名称", "今日盈亏"]].dropna()
    field = "今日盈亏"
else:
    chart_df = df[["名称", "总盈亏"]].dropna()
    field = "总盈亏"

bar = alt.Chart(chart_df).mark_bar(color="#0A84FF").encode(
    x=alt.X("名称:N", axis=alt.Axis(labelAngle=0)),
    y=alt.Y(f"{field}:Q"),
    tooltip=["名称", alt.Tooltip(f"{field}:Q", format=",.2f")]
).properties(height=350)

st.altair_chart(bar, use_container_width=True)

st.caption("更新时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
