import json
import time
from datetime import datetime

import pandas as pd
import streamlit as st

# ====== 可选：密码保护（建议开启）======
def require_password():
    pw_required = "APP_PASSWORD" in st.secrets
    if not pw_required:
        return True

    if "authed" not in st.session_state:
        st.session_state.authed = False

    if st.session_state.authed:
        return True

    st.title("🔒 请输入访问密码")
    pw = st.text_input("Password", type="password")
    if st.button("进入"):
        if pw == st.secrets["APP_PASSWORD"]:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("密码不正确")
    st.stop()


# ====== 行情：优先 akshare，失败则提示 ======
def fetch_prices_akshare(codes):
    """
    codes: list like ["300203", "600759", "601899"]
    return dict {code: last_price}
    """
    import akshare as ak  # noqa

    df = ak.stock_zh_a_spot_em()
    # df columns: 代码, 名称, 最新价 ...
    df = df[["代码", "最新价"]].copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    price_map = {}
    for c in codes:
        row = df.loc[df["代码"] == c]
        if not row.empty:
            price_map[c] = float(row.iloc[0]["最新价"])
    return price_map


def load_holdings():
    with open("holdings.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def money(x):
    return f"¥{x:,.2f}"


def pct(x):
    return f"{x*100:.2f}%"


st.set_page_config(page_title="我的持仓看板", page_icon="📊", layout="wide")
require_password()

data = load_holdings()

st.title("📊 我的A股持仓看板（云端版）")
st.caption("说明：现价来自公开行情源；盈亏为浮动盈亏（未扣手续费/税）。")

# 侧边栏配置
with st.sidebar:
    st.subheader("⚙️ 参数")
    total_assets = st.number_input("总资产（RMB）", value=float(data.get("total_assets_rmb", 0.0)), step=1000.0)
    position_ratio = st.slider("仓位（%）", 0.0, 100.0, float(data.get("position_ratio", 0.0) * 100), 0.1) / 100.0
    refresh = st.button("🔄 刷新行情")
    st.divider()
    st.subheader("🗂️ 快捷链接")
    st.write("（新闻先做轻量版：点开即搜）")
    for h in data["holdings"]:
        code = h["code"]
        name = h["name"]
        st.link_button(f"📰 {name} 新闻", f"https://www.google.com/search?q={name}+{code}+A%E8%82%A1+%E6%96%B0%E9%97%BB")

# 自动刷新：每次进入页面都会拉一次；也支持手动刷新按钮
if refresh:
    st.toast("正在刷新行情…", icon="⏳")

codes = [h["code"] for h in data["holdings"]]

price_map = {}
err = None
try:
    price_map = fetch_prices_akshare(codes)
except Exception as e:
    err = str(e)

# 组装表格
rows = []
for h in data["holdings"]:
    code = h["code"]
    name = h["name"]
    shares = float(h["shares"])
    cost = float(h["cost"])

    last = price_map.get(code, None)
    if last is None:
        mv = None
        pnl = None
        pnl_pct = None
    else:
        mv = last * shares
        pnl = (last - cost) * shares
        pnl_pct = (last / cost - 1.0) if cost > 0 else None

    rows.append(
        {
            "代码": code,
            "名称": name,
            "持股(股)": int(shares),
            "成本价": cost,
            "现价": last,
            "持仓市值": mv,
            "浮盈亏": pnl,
            "盈亏%": pnl_pct,
        }
    )

df = pd.DataFrame(rows)

# 汇总
invested_est = total_assets * position_ratio
mv_sum = float(df["持仓市值"].dropna().sum()) if "持仓市值" in df else 0.0
pnl_sum = float(df["浮盈亏"].dropna().sum()) if "浮盈亏" in df else 0.0

# 现金：用你提供的仓位估算；如果你更希望按“市值反推现金”，后续我可以改成一键切换
cash_est = max(total_assets - invested_est, 0.0)

# 顶部 KPI
c1, c2, c3, c4 = st.columns(4)
c1.metric("总资产", money(total_assets))
c2.metric("估算现金（按仓位）", money(cash_est))
c3.metric("持仓市值（实时）", money(mv_sum))
c4.metric("总浮盈亏（实时）", money(pnl_sum))

if err:
    st.warning(
        "⚠️ 行情拉取失败（可能是部署环境依赖或数据源波动）。你仍可查看持仓与成本；我也可以给你换备用行情源。\n\n"
        f"错误信息：{err}"
    )

# 明细表（美化：盈亏列上色）
st.subheader("📌 持仓明细")
show = df.copy()
for col in ["成本价", "现价", "持仓市值", "浮盈亏"]:
    if col in show.columns:
        show[col] = show[col].map(lambda x: None if pd.isna(x) else round(float(x), 3))

def color_pnl(v):
    if v is None or pd.isna(v):
        return ""
    return "color: #16a34a;" if v > 0 else ("color: #dc2626;" if v < 0 else "")

styled = show.style.applymap(color_pnl, subset=["浮盈亏"]).format(
    {"盈亏%": lambda x: "" if (x is None or pd.isna(x)) else f"{x*100:.2f}%"}
)

st.dataframe(styled, use_container_width=True, height=220)

# 图表
st.subheader("📈 结构视图")
g1, g2 = st.columns(2)

chart_df = df.dropna(subset=["持仓市值"]).copy()
if not chart_df.empty:
    pie = chart_df[["名称", "持仓市值"]].set_index("名称")
    bar = chart_df[["名称", "浮盈亏"]].set_index("名称")

    with g1:
        st.caption("仓位占比（按持仓市值）")
        st.pyplot(pie.plot.pie(y="持仓市值", legend=False, ylabel="").get_figure())

    with g2:
        st.caption("浮盈亏分布")
        st.bar_chart(bar)

st.caption(f"更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")