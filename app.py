import json
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import altair as alt

st.set_page_config(page_title="我的A股持仓看板", page_icon="📈", layout="wide")

# =============================
# iOS 卡片风格（不会裁切内容）
# =============================
st.markdown(
    """
<style>
.block-container { padding-top: 1.0rem; padding-bottom: 2.0rem; }
.ios-card{
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(120,120,120,0.14);
  box-shadow: 0 10px 28px rgba(0,0,0,0.06);
  border-radius: 18px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.kpi-title{ font-size: 0.85rem; opacity: 0.7; margin-bottom: 6px; }
.kpi-value{ font-size: 1.35rem; font-weight: 750; line-height: 1.2; }
.kpi-sub{ font-size: 0.82rem; opacity: 0.65; margin-top: 4px; }
.sidebar-title{ font-weight: 800; font-size: 1.05rem; margin-bottom: 6px; }
</style>
""",
    unsafe_allow_html=True,
)

# =============================
# 工具
# =============================
def load_holdings():
    with open("holdings.json", "r", encoding="utf-8") as f:
        return json.load(f)

def money(x):
    try:
        return f"¥{float(x):,.2f}"
    except:
        return "—"

def pct(x):
    try:
        return f"{float(x)*100:.2f}%"
    except:
        return "—"

def safe_float(x):
    try:
        return float(x)
    except:
        return None

# =============================
# 行情（腾讯：云端最稳）
# 返回：last / prev_close（用于今日盈亏）
# =============================
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
        # payload[3]=现价 payload[4]=昨收（通常如此）
        if len(payload) > 4:
            last = safe_float(payload[3])
            prev_close = safe_float(payload[4])
            if last and last > 0:
                out[code] = {"last": last, "prev_close": prev_close}
    return out

# =============================
# 读取持仓 + 侧边栏
# =============================
data = load_holdings()
holdings = data["holdings"]
codes = [h["code"] for h in holdings]

with st.sidebar:
    st.markdown('<div class="sidebar-title">⚙️ 控制台</div>', unsafe_allow_html=True)

    total_assets = st.number_input("总资产（RMB）", value=float(data.get("total_assets_rmb", 0.0)), step=1000.0)

    # 右侧图展示模式
    pnl_mode = st.radio("盈亏图展示", ["今日盈亏", "总盈亏"], index=0)

    if st.button("🔄 刷新行情"):
        st.rerun()

    st.divider()
    st.markdown("📰 **新闻快捷入口**（点击打开搜索）")
    for h in holdings:
        code = str(h["code"]).zfill(6)
        name = h["name"]
        st.link_button(
            f"{name}（{code}）",
            f"https://www.google.com/search?q={name}+{code}+A%E8%82%A1+%E6%96%B0%E9%97%BB"
        )

# =============================
# 拉行情 + 计算
# =============================
err = None
quotes = {}
try:
    quotes = fetch_prices_tencent(codes)
except Exception as e:
    err = str(e)

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
    prev = q.get("prev_close")

    mv = last * shares if last is not None else None
    total_pnl = (last - cost) * shares if last is not None else None
    total_ret = (last / cost - 1.0) if (last is not None and cost > 0) else None

    today_pnl = (last - prev) * shares if (last is not None and prev is not None) else None
    today_ret = (last / prev - 1.0) if (last is not None and prev is not None and prev > 0) else None

    rows.append({
        "代码": code,
        "名称": name,
        "持股(股)": int(shares),
        "成本价": cost,
        "昨收": prev,
        "现价": last,
        "持仓市值": mv,
        "今日盈亏": today_pnl,
        "今日%": today_ret,
        "总盈亏": total_pnl,
        "总收益率": total_ret,
    })

df = pd.DataFrame(rows)

mv_sum = float(df["持仓市值"].dropna().sum()) if "持仓市值" in df else 0.0
today_sum = float(df["今日盈亏"].dropna().sum()) if "今日盈亏" in df else 0.0
total_sum = float(df["总盈亏"].dropna().sum()) if "总盈亏" in df else 0.0
overall_return = (total_sum / cost_basis) if cost_basis > 0 else 0.0
cash = max(total_assets - mv_sum, 0.0)

# =============================
# 页面标题 + 状态
# =============================
st.title("📈 我的A股持仓看板（云端版）")
# ===== 今日简报（自动生成）=====
def load_daily_brief():
    try:
        with open("daily_brief.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

brief = load_daily_brief()
if brief:
    st.subheader("🗞️ 今日开盘前简报")
    colA, colB = st.columns([1,1])
    with colA:
        st.markdown(f"""
        <div class="ios-card">
          <div class="kpi-title">生成时间</div>
          <div class="kpi-value">{brief.get("generated_at","—")}</div>
          <div class="kpi-sub">开盘前自动更新</div>
        </div>
        """, unsafe_allow_html=True)

    p = brief.get("portfolio", {})
    with colB:
        st.markdown(f"""
        <div class="ios-card">
          <div class="kpi-title">组合概览</div>
          <div class="kpi-value">{money(p.get("today_pnl_rmb",0))}（今日）</div>
          <div class="kpi-sub">总盈亏 {money(p.get("total_pnl_rmb",0))} · 总收益率 {pct(p.get("overall_return",0) or 0)}</div>
        </div>
        """, unsafe_allow_html=True)

    tips = brief.get("risk_tips", [])
    if tips:
        with st.expander("⚠️ 风险提示", expanded=True):
            for t in tips:
                st.write("• " + t)

    with st.expander("📌 今日策略（建议）", expanded=True):
        for s in brief.get("strategy", []):
            st.write("• " + s)

else:
    st.info("今日简报尚未生成：请稍后等待定时任务，或在 GitHub Actions 手动 Run workflow 一次。")
st.caption("说明：今日盈亏基于昨收；总盈亏基于成本价。百分比均显示为 30% 形式。")

if err:
    st.warning(f"行情拉取失败：{err}")

# =============================
# KPI 卡片（完整显示）
# =============================
c1, c2, c3, c4, c5 = st.columns(5)

def card(col, title, value, sub=""):
    with col:
        st.markdown(
            f"""
<div class="ios-card">
  <div class="kpi-title">{title}</div>
  <div class="kpi-value">{value}</div>
  <div class="kpi-sub">{sub}</div>
</div>
""",
            unsafe_allow_html=True,
        )

card(c1, "总资产", money(total_assets))
card(c2, "现金/未用资金", money(cash), "总资产 - 持仓市值")
card(c3, "持仓市值（实时）", money(mv_sum))
card(c4, "今日盈亏", money(today_sum))
card(c5, "总盈亏 / 总收益率", money(total_sum), pct(overall_return))

# =============================
# 明细表（保留，避免“只显示一半”）
# =============================
st.subheader("📌 持仓明细")

def fmt_price(x):
    return "" if (x is None or pd.isna(x)) else f"{float(x):.3f}"

def fmt_money(x):
    return "" if (x is None or pd.isna(x)) else f"{float(x):,.2f}"

def fmt_pct(x):
    return "" if (x is None or pd.isna(x)) else f"{float(x)*100:.2f}%"

def color_posneg(v):
    if v is None or pd.isna(v):
        return ""
    v = float(v)
    if v > 0:
        return "color:#16a34a; font-weight:700;"
    if v < 0:
        return "color:#dc2626; font-weight:700;"
    return ""

styled = df.style.applymap(color_posneg, subset=["今日盈亏", "总盈亏"]).format({
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

# =============================
# 结构视图：左饼图（含现金灰色）+ 右单色柱状（横字）
# =============================
st.subheader("📊 结构视图")
left, right = st.columns(2)

# 饼图数据：持仓 + 现金
pie_df = df[["名称", "持仓市值"]].dropna().copy()
pie_df = pie_df.rename(columns={"持仓市值": "金额"})
pie_df = pd.concat([pie_df, pd.DataFrame([{"名称": "现金/未用资金", "金额": cash}])], ignore_index=True)

with left:
    st.markdown('<div class="ios-card">', unsafe_allow_html=True)
    st.caption("仓位占比（扇形图 / 按金额）")

    pie = alt.Chart(pie_df).mark_arc(outerRadius=125).encode(
        theta=alt.Theta("金额:Q"),
        color=alt.condition(
            alt.datum["名称"] == "现金/未用资金",
            alt.value("#9CA3AF"),  # 灰色
            alt.Color("名称:N", legend=alt.Legend(orient="bottom"))
        ),
        tooltip=["名称:N", alt.Tooltip("金额:Q", format=",.2f")]
    ).properties(height=360)

    st.altair_chart(pie, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="ios-card">', unsafe_allow_html=True)
    st.caption("盈亏分布（单指标更直观）")

    if pnl_mode == "今日盈亏":
        d = df[["名称", "今日盈亏"]].dropna().rename(columns={"今日盈亏": "盈亏"})
    else:
        d = df[["名称", "总盈亏"]].dropna().rename(columns={"总盈亏": "盈亏"})

    if d.empty:
        st.info("暂无可展示数据（可能行情未取到或昨收缺失）")
    else:
        bar = alt.Chart(d).mark_bar(color="#0A84FF").encode(
            x=alt.X("名称:N", sort="-y", axis=alt.Axis(labelAngle=0, title=None)),  # 横向显示
            y=alt.Y("盈亏:Q", axis=alt.Axis(title=None)),
            tooltip=["名称:N", alt.Tooltip("盈亏:Q", format=",.2f")]
        ).properties(height=360)

        st.altair_chart(bar, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

st.caption("更新时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

