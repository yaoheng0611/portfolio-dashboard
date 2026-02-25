import json, os, re
from datetime import datetime, timezone, timedelta
import requests

TZ = timezone(timedelta(hours=8))

def now_cn():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def safe_float(x):
    try:
        return float(x)
    except:
        return None

# -------- Tencent A股行情（稳定，含昨收）
def fetch_tencent_quotes(codes):
    def to_symbol(code):
        code = str(code).zfill(6)
        return ("sh" + code) if code.startswith(("6", "9")) else ("sz" + code)

    symbols = [to_symbol(c) for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    r = requests.get(url, timeout=10)
    r.encoding = "gbk"
    text = r.text

    out = {}
    for line in text.split(";"):
        m = re.search(r'v_(sh|sz)(\d{6})="([^"]*)"', line)
        if not m:
            continue
        code = m.group(2)
        payload = m.group(3).split("~")
        # 常见：payload[3]=现价 payload[4]=昨收
        if len(payload) > 4:
            last = safe_float(payload[3])
            prev = safe_float(payload[4])
            name = payload[1] if len(payload) > 1 else None
            if last and last > 0:
                out[code] = {"name": name, "last": last, "prev_close": prev}
    return out

# -------- 轻量“海外影响”抓取：Yahoo JSON（可能偶发失败，失败不影响主流程）
def fetch_yahoo(symbols):
    # symbols例：["^GSPC","^IXIC","CL=F","GC=F","USDCNY=X"]
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        r = requests.get(url, params={"symbols": ",".join(symbols)}, timeout=10)
        r.raise_for_status()
        j = r.json()
        items = j.get("quoteResponse", {}).get("result", [])
        out = {}
        for it in items:
            sym = it.get("symbol")
            out[sym] = {
                "price": it.get("regularMarketPrice"),
                "change": it.get("regularMarketChange"),
                "changePercent": it.get("regularMarketChangePercent"),
                "time": it.get("regularMarketTime"),
            }
        return out
    except:
        return {}

def fmt_money(x):
    if x is None: return "—"
    return f"¥{x:,.2f}"

def fmt_pct(r):
    if r is None: return "—"
    return f"{r*100:.2f}%"

def main():
    holdings = load_json("holdings.json", {})
    hs = holdings.get("holdings", [])
    total_assets = float(holdings.get("total_assets_rmb", 0))

    codes = [str(h["code"]).zfill(6) for h in hs]
    quotes = fetch_tencent_quotes(codes)

    # 计算持仓表现
    pos = []
    mv_sum = 0.0
    today_pnl_sum = 0.0
    total_pnl_sum = 0.0
    cost_basis = 0.0

    for h in hs:
        code = str(h["code"]).zfill(6)
        name = h.get("name", code)
        shares = float(h.get("shares", 0))
        cost = float(h.get("cost", 0))
        cost_basis += cost * shares

        q = quotes.get(code, {})
        last = q.get("last")
        prev = q.get("prev_close")

        mv = (last * shares) if last is not None else None
        today_pnl = ((last - prev) * shares) if (last is not None and prev is not None) else None
        total_pnl = ((last - cost) * shares) if (last is not None) else None
        total_ret = ((last / cost - 1.0) if (last is not None and cost > 0) else None)

        if mv is not None: mv_sum += mv
        if today_pnl is not None: today_pnl_sum += today_pnl
        if total_pnl is not None: total_pnl_sum += total_pnl

        pos.append({
            "code": code,
            "name": name,
            "shares": int(shares),
            "cost": cost,
            "last": last,
            "prev_close": prev,
            "market_value": mv,
            "today_pnl": today_pnl,
            "total_pnl": total_pnl,
            "total_return": total_ret
        })

    cash = max(total_assets - mv_sum, 0.0)
    overall_return = (total_pnl_sum / cost_basis) if cost_basis > 0 else None

    # 海外/大宗/汇率（可抓则抓，抓不到就略）
    yahoo = fetch_yahoo(["^GSPC","^IXIC","^DJI","CL=F","GC=F","USDCNY=X"])

    # 规则版策略（先能跑起来，后续再升级“精英投顾版”）
    # 你后续想更激进/更保守，我们可以把规则参数化到 settings.json
    risk_tips = []
    for p in pos:
        r = p.get("total_return")
        if r is not None and r <= -0.08:
            risk_tips.append(f"{p['name']} 亏损已达 {fmt_pct(r)}，注意仓位/止损纪律。")
        if r is not None and r >= 0.12:
            risk_tips.append(f"{p['name']} 盈利 {fmt_pct(r)}，可考虑分批止盈/抬保护线。")

    strategy = [
        f"当前现金约 {fmt_money(cash)}，持仓市值约 {fmt_money(mv_sum)}。",
        "今天关注：隔夜风险偏好（美股指数/油金/汇率）→ 可能影响A股情绪与板块轮动。",
        "持仓操作：优先控制回撤，其次再加码强势方向（不做单日梭哈）。",
        "候选关注（激进取向）：电网/贵金属/石油方向里，优先选择趋势更强、成交更活跃、消息催化更明确的标的。"
    ]

    brief = {
        "generated_at": now_cn(),
        "portfolio": {
            "total_assets_rmb": total_assets,
            "cash_rmb": cash,
            "market_value_rmb": mv_sum,
            "today_pnl_rmb": today_pnl_sum,
            "total_pnl_rmb": total_pnl_sum,
            "overall_return": overall_return
        },
        "holdings": pos,
        "overnight": {
            "yahoo": yahoo  # 前端可以选择展示或隐藏
        },
        "risk_tips": risk_tips[:6],
        "strategy": strategy
    }

    save_json("daily_brief.json", brief)
    print("daily_brief.json generated:", brief["generated_at"])

if __name__ == "__main__":
    main()
