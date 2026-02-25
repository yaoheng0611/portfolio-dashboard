import json
from datetime import datetime
import pandas as pd
import streamlit as st
import requests
import re

st.set_page_config(page_title="我的A股持仓看板", page_icon="📊", layout="wide")

# =============================
# 读取持仓文件（UTF-8安全）
# =============================
def load_holdings():
    with open("holdings.json", "r", encoding="utf-8") as f:
        return json.load(f)

# =============================
# 行情源1：akshare
# =============================
def fetch_prices_akshare(codes):
    import akshare as ak
    df = ak.stock_zh_a_spot_em()
    df = df[["代码", "最新价"]].copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    price_map = {}
    for c in codes:
        row = df.loc[df["代码"] == c]
        if not row.empty:
            price_map[c] = float(row.iloc[0]["最新价"])
    return price_map

# =============================
# 行情源2：腾讯接口（备用）
# =============================
def fetch_prices_tencent(codes):
    def to_symbol(code):
        code = str(code).zfill(6)
        if code.startswith(("6", "9")):
            return "sh" + code
        else:
            return "sz" + code

    symbols = [to_symbol(c) for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)

    r = requests.get(url, timeout=8)
    r.encoding = "gbk"
    text = r.text

    price_map = {}

    for line in text.split(";"):
        if "v_" not in line:
            continue
        m = re.search(r'v_(sh|sz)(\d{6})="([^"]*)"', line)
        if not m:
            continue
        code = m.group(2)
        payload = m.group(3).split("~")
        if len(payload) > 3:
            try:
                price = float(payload[3])
                if price > 0:
                    price_map[code] = price
            except:
                pass
    return price_map

# =============================
# 页面开始
# =============================
st.title("📊 我的A股持仓看板（云端版）")

data = load_holdings()
total_assets = float(data.get("total_assets_rmb", 0))
position_ratio = float(data.get("position_ratio", 0))
holdings = data["holdings"]

codes = [h["code"] for h in holdings]

price_map = {}
error_msg = ""

# 先尝试 akshare
try:
    price_map = fetch_prices_akshare(codes)
except Exception as e:
    error_msg = f"akshare失败：{e}"

# 如果失败则切换腾讯
if not price_map:
    try:
        price_map = fetch_prices_tencent(codes)
        if error_msg:
            error_msg += "；已切换腾讯行情"
    except Exception as e2:
        error_msg += f"；腾讯行情也失败：{e2}"

# =============================
# 生成数据表
# =============================
rows = []
for h in holdings:
    code = h["code"]
    name = h["name"]
    shares = float(h["shares"])
    cost = float(h["cost"])

    last = price_map.get(code)

    if last:
        market_value = last * shares
        pnl = (last - cost) * shares
        pnl_pct = (last / cost - 1)
    else:
        market_value = None
        pnl = None
        pnl_pct = None

    rows.append({
        "代码": code,
        "名称": name,
        "持股": shares,
        "成本价": cost,
        "现价": last,
        "持仓市值": market_value,
        "浮盈亏": pnl,
        "盈亏%": pnl_pct
    })

df = pd.DataFrame(rows)

total_mv = df["持仓市值"].dropna().sum() if "持仓市值" in df else 0
total_pnl = df["浮盈亏"].dropna().sum() if "浮盈亏" in df else 0
cash_est = total_assets - total_mv

# =============================
# 顶部统计
# =============================
col1, col2, col3, col4 = st.columns(4)

col1.metric("总资产", f"¥{total_assets:,.2f}")
col2.metric("估算现金", f"¥{cash_est:,.2f}")
col3.metric("持仓市值（实时）", f"¥{total_mv:,.2f}")
col4.metric("总浮盈亏（实时）", f"¥{total_pnl:,.2f}")

if error_msg:
    st.warning("行情部分来源失败，但已自动尝试备用数据源。\n\n" + error_msg)

# =============================
# 表格展示
# =============================
st.subheader("📌 持仓明细")
st.dataframe(df)

# =============================
# 图表
# =============================
if total_mv > 0:
    st.subheader("📈 仓位分布")
    st.bar_chart(df.set_index("名称")["持仓市值"])

st.caption("更新时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
