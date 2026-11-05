# -*- coding: utf-8 -*-
"""매일 저녁 실행: 매크로 지표(macro.json) + 투자자별 수급(data.json, days/*.json)"""
import csv, io, json, os, time
import datetime as dt
from pykrx import stock

# ---------------- 설정 ----------------
INVESTORS = ["연기금", "사모", "투신", "기관합계", "외국인", "개인"]   # data.json 의 v 순서
GROUPS = {
    "pension": ["연기금"],
    "foreign": ["외국인"],
    "inst3":   ["연기금", "사모", "투신"],
    "inst3f":  ["연기금", "사모", "투신", "외국인"],
}
TRACK = ["연기금", "사모", "투신", "외국인"]   # 연속 일수 계산에 필요한 투자자
MARKETS = ["KOSPI", "KOSDAQ"]
HIST_DAYS = 125    # 거래일 목록 길이 (연속 일수 처음 계산, 이동평균 120일에 사용)
MA_DAYS = 120      # 정배열·역배열 판단에 쓰는 기간(거래일) — 5·10·20·60·120일선
DETAIL_DAYS = 20   # 종목 상세(표·차트)에 보여줄 기간(거래일)
MIN_AMT = 10.0     # 순위에 올릴 최소 금액(억 원)
TOP_N = 15
SLEEP = 0.7

MACRO = [  # (키, 이름, 야후 티커, 구분)
    ("dow",    "다우",              "^DJI",    "지수"),
    ("nasdaq", "나스닥",            "^IXIC",   "지수"),
    ("sp500",  "S&P 500",           "^GSPC",   "지수"),
    ("sox",    "필라델피아 반도체",  "^SOX",    "지수"),
    ("kospi",  "코스피",            "^KS11",   "지수"),
    ("kosdaq", "코스닥",            "^KQ11",   "지수"),
    ("us10y",  "미국 10년물 금리",   "^TNX",    "매크로"),
    ("wti",    "WTI 유가",          "CL=F",    "매크로"),
    ("btc",    "비트코인",          "BTC-USD", "매크로"),
]
MACRO_DAYS = 200   # 달력 기준 보관 기간

# 미국 히트맵: 업종별 주요 종목 (시가총액은 실행 때마다 받아옴)
HEAT = {
    "기술": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "AMD", "CRM", "ADBE", "CSCO", "QCOM", "TXN", "INTC",
             "MU", "AMAT", "LRCX", "KLAC", "IBM", "NOW", "PLTR", "ANET"],
    "커뮤니케이션": ["GOOGL", "META", "NFLX", "DIS", "TMUS", "VZ", "T"],
    "경기소비재": ["AMZN", "TSLA", "HD", "MCD", "LOW", "BKNG", "NKE", "SBUX"],
    "금융": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "AXP", "C", "BLK", "SCHW"],
    "헬스케어": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "ABT", "ISRG", "AMGN", "PFE"],
    "산업재": ["GE", "CAT", "RTX", "HON", "UNP", "BA", "DE", "LMT", "UPS"],
    "필수소비재": ["WMT", "COST", "PG", "KO", "PEP", "PM"],
    "에너지": ["XOM", "CVX", "COP"],
    "유틸리티·부동산·소재": ["NEE", "SO", "PLD", "AMT", "LIN"],
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Referer": "https://www.cnn.com/"}

DIR = os.path.dirname(os.path.abspath(__file__))
DAYS_DIR = os.path.join(DIR, "days")
PX_DIR = os.path.join(DIR, "px")


def load(name, default):
    try:
        with open(os.path.join(DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(name, obj):
    path = os.path.join(DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def kst_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=9)


def eok(won):
    return round(float(won) / 1e8, 1)


# ---------------- 매크로 ----------------
def get_retry(url, tries=3, timeout=60):
    import requests
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(5 * (i + 1))
    raise last


def fetch_market_flows():
    """코스피·코스닥 시장 전체 투자자별 순매수 (억 원): [날짜, 개인, 외국인, 기관]"""
    now = kst_now()
    start = (now - dt.timedelta(days=MACRO_DAYS)).strftime("%Y%m%d")
    out = {}
    for key, mk in (("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")):
        df = stock.get_market_trading_value_by_date(start, now.strftime("%Y%m%d"), mk)
        time.sleep(SLEEP)
        fcol = "외국인합계" if "외국인합계" in df.columns else "외국인"
        out[key] = [[d.strftime("%Y-%m-%d"), eok(r["개인"]), eok(r[fcol]), eok(r["기관합계"])]
                    for d, r in df.iterrows()]
        print("시장 수급", key, out[key][-1] if out[key] else "없음")
    return out


def isin_check(body):
    """ISIN 마지막 검증숫자"""
    digits = "".join(str(int(c, 36)) for c in body)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d // 10 + d % 10
    return str((10 - total % 10) % 10)


def fetch_futures_flows():
    """코스피200 선물 투자자별 순매수 (다음 금융): [날짜, 개인, 외국인, 기관]  ※ 시험 단계
    다음 금융의 선물 투자자 값은 월물별이 아니라 전 월물 합계라, 상장된 월물 하나만 조회하면 됨"""
    import requests
    now = kst_now()
    cands = []   # 아직 만기 전인 가까운 월물부터 시도
    for yy in (now.year, now.year + 1):
        for mnum, mm in ((3, "3"), (6, "6"), (9, "9"), (12, "C")):
            if yy == now.year and mnum < now.month:
                continue
            body = f"KR4A01{str(yy)[-1]}{mm}000"
            cands.append(body + isin_check(body))
    headers = {"User-Agent": UA["User-Agent"], "Referer": "https://finance.daum.net/domestic/futures"}
    for isin in cands:
        url = f"https://finance.daum.net/api/future/{isin}/days?page=1&perPage=100&pagination=true"
        try:
            r = requests.get(url, headers=headers, timeout=30)
            j = r.json()
        except Exception as e:
            print("선물 시험", isin, "실패", e)
            continue
        data = j.get("data") if isinstance(j, dict) else j
        if not data:
            print("선물 시험", isin, "자료 없음", str(j)[:200])
            continue
        print("선물 시험", isin, "항목:", sorted(data[0].keys()))
        print("선물 시험 첫 줄:", data[0])

        def pick(d, word):   # 계약 수(volume) 항목을 먼저, 없으면 다른 순매수 항목
            found = [k for k, v in d.items() if word in k.lower()
                     and ("straight" in k.lower() or "net" in k.lower()) and isinstance(v, (int, float))]
            found.sort(key=lambda k: 0 if "volume" in k.lower() else 1)
            return found[0] if found else None
        # 다음 금융 항목 이름: 개인 privateSettlement, 외국인 foreignSettlement, 기관 institutionSettlement (계약 수)
        known = {"individual": "privateSettlement", "foreign": "foreignSettlement", "institution": "institutionSettlement"}
        keys = {w: (known[w] if known[w] in data[0] else pick(data[0], w)) for w in known}
        print("선물 시험 쓰는 항목:", keys)
        if not all(keys.values()):
            raise RuntimeError("선물 항목 이름을 못 찾음")
        rows, px = [], []
        for d in data:
            ds = str(d.get("date") or d.get("tradeDate") or "")[:10]
            if len(ds) == 10:
                rows.append([ds, float(d[keys["individual"]] or 0), float(d[keys["foreign"]] or 0),
                             float(d[keys["institution"]] or 0)])
                if d.get("tradePrice") is not None:
                    px.append([ds, round(float(d["tradePrice"]), 2)])
        rows.sort()
        px.sort()
        print("선물 시험 결과", len(rows), "일", rows[-2:])
        if not rows or rows[-1][0] < (now - dt.timedelta(days=10)).strftime("%Y-%m-%d"):
            print("선물 시험", isin, "최근 자료가 아님, 다음 월물 시도")
            continue
        unit = "계약" if ("settlement" in keys["foreign"].lower() or "volume" in keys["foreign"].lower()) else "다음 금융 기준"
        top = max(data, key=lambda d: str(d.get("date", "")))
        return {"unit": unit, "rows": rows, "keys": keys, "px": px,
                "chg": top.get("changePrice"), "rate": top.get("changeRate"),
                "at": kst_now().strftime("%Y-%m-%d %H:%M")}
    raise RuntimeError("선물 자료를 못 받음")


EVE = [  # (구분, [(이름, 야후 티커)])
    ("미국 선물", [("나스닥100 선물", "NQ=F"), ("S&P500 선물", "ES=F"), ("다우 선물", "YM=F")]),
    ("반도체·빅테크 프리장", [("SK하이닉스 ADR", "SKHY"), ("엔비디아", "NVDA"), ("AMD", "AMD"), ("마이크론", "MU"), ("브로드컴", "AVGO"),
                         ("TSMC", "TSM"), ("반도체 ETF", "SOXX"), ("애플", "AAPL"), ("마이크로소프트", "MSFT")]),
    ("유럽 증시", [("독일 DAX", "^GDAXI"), ("유로스톡스50", "^STOXX50E"), ("영국 FTSE", "^FTSE")]),
    ("유가·금리·환율", [("WTI 유가", "CL=F"), ("미국 10년물", "^TNX"), ("달러/원", "KRW=X")]),
]


def fetch_evening():
    """저녁 8시 전 체크: 미국 선물, 프리장 반도체·빅테크, 유럽 증시, 유가·금리·환율"""
    import yfinance as yf
    groups = []
    for gname, lst in EVE:
        items = []
        for name, t in lst:
            try:
                info = yf.Ticker(t).info
                state = str(info.get("marketState", ""))
                pc, pp = info.get("preMarketChangePercent"), info.get("preMarketPrice")
                if state.startswith("PRE") and pc is not None and pp:
                    c, v, tag = float(pc), float(pp), "프리"
                else:
                    c = float(info.get("regularMarketChangePercent") or 0)
                    v = float(info.get("regularMarketPrice") or 0)
                    tag = ""
                if t == "^TNX" and v > 20:
                    v = v / 10
                items.append({"n": name, "t": t, "c": round(c, 2), "v": round(v, 3 if t == "^TNX" else 2), "tag": tag})
            except Exception as e:
                print("저녁 체크 건너뜀", t, e)
            time.sleep(0.3)
        groups.append({"name": gname, "items": items})

    def avg(i):
        xs = [x["c"] for x in groups[i]["items"]]
        return sum(xs) / len(xs) if xs else 0
    nq = next((x["c"] for x in groups[0]["items"] if x["t"] == "NQ=F"), 0)
    sig = [("나스닥 선물", nq), ("반도체 프리장", avg(1)), ("유럽 증시", avg(2))]
    print("저녁 체크", [(n, round(v, 2)) for n, v in sig])
    return {"at": kst_now().strftime("%Y-%m-%d %H:%M"), "groups": groups,
            "sig": [{"n": n, "c": round(v, 2)} for n, v in sig]}


def fetch_heatmap():
    """미국 주요 종목 등락. 프리장이면 프리장 등락, 아니면 직전 정규장 등락"""
    import yfinance as yf
    items, pre = [], 0
    for sec, ts in HEAT.items():
        for t in ts:
            try:
                info = yf.Ticker(t).info
                cap = info.get("marketCap") or 0
                state = str(info.get("marketState", ""))
                pc = info.get("preMarketChangePercent")
                if state.startswith("PRE") and pc is not None and info.get("preMarketPrice"):
                    chg, pre = float(pc), pre + 1
                else:
                    chg = float(info.get("regularMarketChangePercent") or 0)
                if cap:
                    items.append({"t": t, "s": sec, "cap": round(cap / 1e9, 1), "c": round(chg, 2)})
            except Exception as e:
                print("히트맵 건너뜀", t, e)
            time.sleep(0.3)
    if len(items) < 20:
        raise RuntimeError(f"종목을 {len(items)}개만 받음")
    mode = "pre" if pre > len(items) / 2 else "reg"
    print("히트맵", len(items), "종목,", "프리장" if mode == "pre" else "정규장", "기준")
    return {"mode": mode, "at": kst_now().strftime("%Y-%m-%d %H:%M"), "items": items}


def fetch_macro():
    import yfinance as yf
    prev = load("macro.json", {})          # 실패한 항목은 지난번 자료를 그대로 씀
    prev_items = {i["k"]: i for i in prev.get("items", [])}
    cutoff = (kst_now() - dt.timedelta(days=MACRO_DAYS)).strftime("%Y-%m-%d")
    out = {"updated": kst_now().strftime("%Y-%m-%d %H:%M"), "items": [], "fg": None, "hy": None}

    for key, name, ticker, grp in MACRO:
        try:
            df = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=False)
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            if df.empty:
                raise ValueError("빈 자료")
            scale = 0.1 if ticker == "^TNX" and float(df["Close"].iloc[-1]) > 20 else 1
            nd = 3 if ticker == "^TNX" else 2
            rows = []
            for d, r in df.iterrows():
                ds = d.strftime("%Y-%m-%d")
                if ds >= cutoff:
                    rows.append([ds] + [round(float(r[c]) * scale, nd) for c in ("Open", "High", "Low", "Close")])
            out["items"].append({"k": key, "n": name, "g": grp, "c": rows})
        except Exception as e:
            print("매크로 건너뜀(지난 자료 사용)", name, e)
            out["items"].append(prev_items.get(key, {"k": key, "n": name, "g": grp, "c": []}))

    try:  # 리튬: 중국 광저우선물거래소 탄산리튬 선물 연결(LC0), 위안/톤 — akshare(시나 금융) 사용
        import akshare as ak
        df = ak.futures_zh_daily_sina(symbol="LC0")
        print("리튬 시험 열:", list(df.columns), "마지막:", df.tail(1).to_dict("records"))
        rows = []
        for _, r in df.iterrows():
            ds = str(r["date"])[:10]
            if ds >= cutoff:
                rows.append([ds] + [round(float(r[c]), 0) for c in ("open", "high", "low", "close")])
        if not rows:
            raise ValueError("빈 자료")
        lith = {"k": "lithium", "n": "탄산리튬 (중국 선물)", "g": "매크로", "c": rows}
    except Exception as e:
        print("리튬 건너뜀(지난 자료 사용)", e)
        lith = prev_items.get("lithium", {"k": "lithium", "n": "탄산리튬 (중국 선물)", "g": "매크로", "c": []})
    pos = next((i + 1 for i, it in enumerate(out["items"]) if it["k"] == "wti"), len(out["items"]))
    out["items"].insert(pos, lith)

    try:  # 하이일드 스프레드 (미국 연준 FRED, 단위 %)
        # FRED는 브라우저처럼 꾸민 요청을 GitHub 서버에서 보내면 응답을 안 해서, 기본 요청으로 받음
        import urllib.request
        text = None
        for i in range(3):
            try:
                with urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2", timeout=60) as f:
                    text = f.read().decode("utf-8")
                break
            except Exception as e:
                print("하이일드 재시도", i + 1, e)
                time.sleep(5 * (i + 1))
        if text is None:
            raise RuntimeError("FRED 응답 없음")
        rows = []
        for row in list(csv.reader(io.StringIO(text)))[1:]:
            if len(row) >= 2 and row[1] not in ("", ".") and row[0] >= cutoff:
                rows.append([row[0], round(float(row[1]), 2)])
        out["hy"] = rows
    except Exception as e:
        print("하이일드 건너뜀(지난 자료 사용)", e)
        out["hy"] = prev.get("hy")

    try:  # 공포탐욕지수 (CNN, 비공식)
        r = get_retry("https://production.dataviz.cnn.io/index/fearandgreed/graphdata")
        j = r.json()
        hist = []
        for p in j.get("fear_and_greed_historical", {}).get("data", []):
            ds = dt.datetime.utcfromtimestamp(p["x"] / 1000).strftime("%Y-%m-%d")
            if ds >= cutoff:
                hist.append([ds, round(float(p["y"]), 1)])
        fg = j.get("fear_and_greed", {})
        out["fg"] = {"score": round(float(fg.get("score", 0)), 1), "rating": fg.get("rating", ""), "hist": hist}
    except Exception as e:
        print("공포탐욕 건너뜀(지난 자료 사용)", e)
        out["fg"] = prev.get("fg")

    try:
        out["eve"] = fetch_evening()
    except Exception as e:
        print("저녁 체크 건너뜀(지난 자료 사용)", e)
        out["eve"] = prev.get("eve")
    try:
        out["heat"] = fetch_heatmap()
    except Exception as e:
        print("히트맵 건너뜀(지난 자료 사용)", e)
        out["heat"] = prev.get("heat")
    try:
        out["flows"] = fetch_market_flows()
    except Exception as e:
        print("시장 수급 건너뜀(지난 자료 사용)", e)
        out["flows"] = prev.get("flows")
    try:
        out["fut"] = fetch_futures_flows()
    except Exception as e:
        print("선물 수급 건너뜀(지난 자료 사용)", e)
        out["fut"] = prev.get("fut")

    save("macro.json", out)
    print("매크로 완료")


# ---------------- 수급 ----------------
def business_days():
    """거래일 목록. 장중에도 오늘이 들어가도록 시장 전체 투자자별 거래 자료로 판단"""
    now = kst_now()
    start = (now - dt.timedelta(days=HIST_DAYS * 2)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    days = set()
    try:
        df = stock.get_market_trading_value_by_date(start, end, "KOSPI")
        days |= {d.strftime("%Y%m%d") for d in df.index}
        time.sleep(SLEEP)
    except Exception as e:
        print("거래일 확인(수급) 실패", e)
    df = stock.get_market_ohlcv(start, end, "005930")
    days |= {d.strftime("%Y%m%d") for d in df.index}
    return sorted(days)[-HIST_DAYS:]


def fetch_day(day, investors):
    """{투자자: {종목코드: (종목명, 시장, 억원)}}"""
    out = {}
    for inv in investors:
        got = {}
        for m in MARKETS:
            df = stock.get_market_net_purchases_of_equities(day, day, m, inv)
            time.sleep(SLEEP)
            for code, row in df.iterrows():
                got[code] = (row["종목명"], m, eok(row["순매수거래대금"]))
        if not got:
            raise SystemExit(f"{day} {inv} 자료를 못 받았어요. KRX_ID / KRX_PW 설정을 확인하세요.")
        out[inv] = got
    return out


def fetch_prices(day):
    """{종목코드: (종가, 등락률)}"""
    out = {}
    for m in MARKETS:
        df = stock.get_market_ohlcv(day, market=m)
        time.sleep(SLEEP)
        for code, r in df.iterrows():
            if float(r["종가"]) > 0:
                out[code] = (int(r["종가"]), round(float(r["등락률"]), 2))
    return out


def step(prev, v):
    """어제까지 연속 일수(prev)에 오늘 금액(v) 반영. +는 매수 일수, -는 매도 일수"""
    if v > 0:
        return prev + 1 if prev > 0 else 1
    if v < 0:
        return prev - 1 if prev < 0 else -1
    return 0


def apply_day(streaks, day_vals):
    for g, invs in GROUPS.items():
        sums = {}
        for inv in invs:
            for code, (_, _, amt) in day_vals[inv].items():
                sums[code] = sums.get(code, 0) + amt
        cur, new = streaks[g], {}
        for code in set(cur) | set(sums):
            s = step(cur.get(code, 0), round(sums.get(code, 0), 1))
            if s:
                new[code] = s
        streaks[g] = new


INST_COLS = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]


def row_values(r):
    return [eok(r["연기금"]), eok(r["사모"]), eok(r["투신"]),
            eok(sum(r[k] for k in INST_COLS if k in r)), eok(r["외국인"]), eok(r["개인"])]


def fetch_detail(code, days, today):
    """ETF 등 개별 조회 종목용: [날짜, 종가, 등락률, 연기금, 사모, 투신, 기관, 외국인, 개인] (최근이 위)"""
    start = days[-(DETAIL_DAYS + 1)]
    tv = stock.get_market_trading_value_by_date(start, today, code, detail=True)
    time.sleep(SLEEP)
    px = stock.get_market_ohlcv(start, today, code)
    time.sleep(SLEEP)
    flows = {d.strftime("%Y%m%d"): r for d, r in tv.iterrows()}
    closes = [(d.strftime("%Y%m%d"), float(r["종가"])) for d, r in px.iterrows()]
    rows = []
    for i in range(1, len(closes)):
        d, c = closes[i]
        prev = closes[i - 1][1]
        pct = round((c / prev - 1) * 100, 2) if prev else 0.0
        r = flows.get(d)
        rows.append([f"{d[4:6]}/{d[6:]}", int(c), pct] + (row_values(r) if r is not None else [None] * 6))
    return rows[::-1]


def run_flows():
    days = business_days()
    try:
        first = fetch_day(days[-1], INVESTORS)
    except SystemExit as e:
        # 장 마감 직전·직후 등 거래소가 종목별 자료를 잠시 안 주는 때가 있음 → 직전 거래일 기준으로 만듦
        print("오늘 종목별 자료가 아직 없어 직전 거래일 기준으로 만들어요:", e)
        days = days[:-1]
        first = fetch_day(days[-1], INVESTORS)
    today = days[-1]
    detail_days = days[-DETAIL_DAYS:]
    cache = {today: first}

    # 1) 날짜별 파일 (전 종목 종가·등락률·투자자별 금액) — 오늘은 매번 새로, 지난 날은 없을 때만
    for d in detail_days:
        path = os.path.join(DAYS_DIR, d + ".json")
        if d != today and os.path.exists(path):
            continue
        print("날짜별 파일", d)
        vals = cache.get(d) or fetch_day(d, INVESTORS)
        cache[d] = vals
        prices = fetch_prices(d)
        rec = {}
        for code in set(prices) | set(vals[INVESTORS[0]]):
            px = prices.get(code, (None, None))
            rec[code] = [px[0], px[1]] + [vals[inv].get(code, (0, 0, 0))[2] for inv in INVESTORS]
        save(os.path.join("days", d + ".json"), rec)
    if os.path.isdir(DAYS_DIR):
        for f in os.listdir(DAYS_DIR):
            if f.endswith(".json") and f[:-5] not in detail_days:
                os.remove(os.path.join(DAYS_DIR, f))

    # 1-2) 종가 기록 (정배열·역배열 판단용) — 오늘은 매번 새로, 지난 날은 없을 때만
    ma_days = days[-MA_DAYS:]
    closes = {}
    for d in ma_days:
        path = os.path.join(PX_DIR, d + ".json")
        if d != today and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                closes[d] = json.load(f)
            continue
        print("종가 기록", d)
        closes[d] = {c: v[0] for c, v in fetch_prices(d).items()}
        save(os.path.join("px", d + ".json"), closes[d])
    if os.path.isdir(PX_DIR):
        for f in os.listdir(PX_DIR):
            if f.endswith(".json") and f[:-5] not in ma_days:
                os.remove(os.path.join(PX_DIR, f))

    def align(code):
        """5·10·20·60·120일선 기준.
        1: 5>10>20>60>120 완전 정배열, -1: 완전 역배열,
        2/-2: 완전하진 않을 때 20일선이 60일선 위/아래, 0: 판단 불가(상장 120일 미만 등)"""
        xs = [closes[d][code] for d in ma_days if code in closes.get(d, {})]
        if len(xs) < MA_DAYS:
            return 0
        m = [sum(xs[-n:]) / n for n in (5, 10, 20, 60, 120)]
        if all(m[i] > m[i + 1] for i in range(4)):
            return 1
        if all(m[i] < m[i + 1] for i in range(4)):
            return -1
        return 2 if m[2] > m[3] else -2

    # 2) 연속 일수: 어제까지는 저장해 두고 이어서 계산, 오늘 값은 매번 새로 반영
    #    (같은 날 다시 실행해도 두 번 세지 않도록)
    state = load("state.json", {})
    if state.get("date") not in days[:-1]:
        state = {"date": None, "s": {g: {} for g in GROUPS}}
    for g in GROUPS:
        state["s"].setdefault(g, {})
    for d in [d for d in days[:-1] if state["date"] is None or d > state["date"]]:
        print("연속 일수 계산", d)
        apply_day(state["s"], cache.get(d) or fetch_day(d, TRACK))
        state["date"] = d
    save("state.json", state)
    final = {g: dict(v) for g, v in state["s"].items()}
    apply_day(final, cache[today])

    # 3) 종목별 오늘 값 + 그룹별 연속 일수
    gkeys = list(GROUPS)
    stocks = {}
    for i, inv in enumerate(INVESTORS):
        for code, (name, m, amt) in cache[today][inv].items():
            s = stocks.setdefault(code, {"n": name, "m": m, "v": [0] * len(INVESTORS)})
            s["v"][i] = amt
    for code, s in stocks.items():
        s["s"] = [final[g].get(code, 0) for g in gkeys]
        s["a"] = align(code)

    # 4) watchlist.json 에만 있는 종목(ETF 등)은 따로 받기
    extra = {}
    for w in load("watchlist.json", []):
        code = w.get("code", "")
        if not code or code in stocks:
            continue
        try:
            df = stock.get_market_trading_value_by_date(days[0], today, code, detail=True)
            time.sleep(SLEEP)
            if df.empty or df.index[-1].strftime("%Y%m%d") != today:
                continue
            ss = {g: 0 for g in gkeys}
            for _, r in df.iterrows():
                for g, invs in GROUPS.items():
                    ss[g] = step(ss[g], round(sum(eok(r[i]) for i in invs), 1))
            stocks[code] = {"n": w.get("name", code), "m": "기타",
                            "v": row_values(df.iloc[-1]), "s": [ss[g] for g in gkeys]}
            extra[code] = fetch_detail(code, days, today)
        except Exception as e:
            print("건너뜀", code, e)
    save("extra.json", extra)

    # 5) 탭별 연속 순매수 / 순매도 순위: 연속 일수 → 당일 금액
    def gval(s, g):
        return round(sum(s["v"][INVESTORS.index(i)] for i in GROUPS[g]), 1)

    lists = {}
    for gi, g in enumerate(gkeys):
        buy = [c for c, s in stocks.items() if s["s"][gi] > 0 and gval(s, g) >= MIN_AMT]
        buy.sort(key=lambda c: (-stocks[c]["s"][gi], -gval(stocks[c], g)))
        sell = [c for c, s in stocks.items() if s["s"][gi] < 0 and gval(s, g) <= -MIN_AMT]
        sell.sort(key=lambda c: (stocks[c]["s"][gi], gval(stocks[c], g)))
        lists[g] = {"buy": buy[:TOP_N], "sell": sell[:TOP_N]}

    save("data.json", {
        "date": f"{today[:4]}-{today[4:6]}-{today[6:]}",
        "updated": kst_now().strftime("%Y-%m-%d %H:%M"),
        # 오늘 자료를 장 마감(15:30) 뒤에 받았으면 확정, 장중이면 잠정
        "final": not (today == kst_now().strftime("%Y%m%d") and kst_now().strftime("%H%M") < "1600"),
        "minAmt": MIN_AMT,
        "groups": gkeys,
        "days": detail_days[::-1],
        "stocks": stocks,
        "lists": lists,
    })

    for old in ("history.json", "detail.json"):   # 예전 방식 파일 정리
        p = os.path.join(DIR, old)
        if os.path.exists(p):
            os.remove(p)
    print("수급 완료", today, len(stocks), "종목")


def main():
    try:
        fetch_macro()
    except Exception as e:
        print("매크로 실패", e)
    run_flows()


if __name__ == "__main__":
    main()
