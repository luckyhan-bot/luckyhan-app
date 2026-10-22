# -*- coding: utf-8 -*-
"""매일 장 마감 후 투자자별 순매수 금액을 모아 data.json 으로 저장"""
import json, os, time
import datetime as dt
from pykrx import stock

INVESTORS = ["연기금", "사모", "투신", "기관합계", "외국인", "개인"]
MARKETS = ["KOSPI", "KOSDAQ"]
HIST_DAYS = 40   # 연속 일수 계산에 쓰는 기간(거래일)
MIN_AMT = 10.0   # 연속 표에 올릴 최소 금액(억 원) - 소액 종목 걸러내기
TOP_N = 15
DIR = os.path.dirname(os.path.abspath(__file__))


def load(name, default):
    try:
        with open(os.path.join(DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(name, obj):
    with open(os.path.join(DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def eok(won):
    return round(float(won) / 1e8, 1)


def kst_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=9)


def business_days():
    now = kst_now()
    start = (now - dt.timedelta(days=HIST_DAYS * 2)).strftime("%Y%m%d")
    df = stock.get_market_ohlcv(start, now.strftime("%Y%m%d"), "005930")
    return [d.strftime("%Y%m%d") for d in df.index][-HIST_DAYS:]


def net_by_market(day, investor):
    out = {}
    for m in MARKETS:
        df = stock.get_market_net_purchases_of_equities(day, day, m, investor)
        time.sleep(0.5)
        for code, row in df.iterrows():
            out[code] = (row["종목명"], m, eok(row["순매수거래대금"]))
    return out


def count_streak(values):
    """values: 최근 날짜부터 거꾸로 된 금액 목록. +면 연속 매수 일수, -면 연속 매도 일수"""
    if not values or values[0] == 0:
        return 0
    sign = 1 if values[0] > 0 else -1
    n = 0
    for v in values:
        if v * sign > 0:
            n += 1
        else:
            break
    return n * sign


def main():
    days = business_days()
    today = days[-1]

    # 1) 연기금 과거 기록 (없는 날만 받아오기)
    hist = load("history.json", {})
    for d in days:
        if not hist.get(d):   # 비어 있는 날도 다시 받기
            print("기록 받는 중", d)
            hist[d] = {c: v[2] for c, v in net_by_market(d, "연기금").items() if v[2] != 0}
    hist = {d: hist[d] for d in days}
    save("history.json", hist)

    # 2) 오늘 투자자별 금액
    stocks = {}
    for i, inv in enumerate(INVESTORS):
        for code, (name, m, amt) in net_by_market(today, inv).items():
            s = stocks.setdefault(code, {"n": name, "m": m, "v": [0] * len(INVESTORS)})
            s["v"][i] = amt

    if not stocks:
        raise SystemExit("한국거래소 자료를 못 받았어요. KRX_ID / KRX_PW 설정을 확인하세요.")

    rev = list(reversed(days))
    for code, s in stocks.items():
        s["s"] = count_streak([hist[d].get(code, 0) for d in rev])

    # 3) 관심 종목 중 위에 없는 것(ETF 등)은 종목별로 따로 받기
    inst = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]
    for w in load("watchlist.json", []):
        code = w.get("code", "")
        if not code or code in stocks:
            continue
        try:
            df = stock.get_market_trading_value_by_date(days[0], today, code, detail=True)
            time.sleep(0.5)
            if df.empty or df.index[-1].strftime("%Y%m%d") != today:
                continue
            r = df.iloc[-1]
            v = [eok(r["연기금"]), eok(r["사모"]), eok(r["투신"]),
                 eok(sum(r[c] for c in inst if c in r)), eok(r["외국인"]), eok(r["개인"])]
            stocks[code] = {"n": w.get("name", code), "m": "기타", "v": v,
                            "s": count_streak([float(x) for x in df["연기금"]][::-1])}
        except Exception as e:
            print("건너뜀", code, e)

    # 4) 연속 순매수 / 순매도 순위: 연속 일수 → 당일 금액
    buy = [c for c, s in stocks.items() if s["s"] > 0 and s["v"][0] >= MIN_AMT]
    buy.sort(key=lambda c: (-stocks[c]["s"], -stocks[c]["v"][0]))
    sell = [c for c, s in stocks.items() if s["s"] < 0 and s["v"][0] <= -MIN_AMT]
    sell.sort(key=lambda c: (stocks[c]["s"], stocks[c]["v"][0]))

    save("data.json", {
        "date": f"{today[:4]}-{today[4:6]}-{today[6:]}",
        "updated": kst_now().strftime("%Y-%m-%d %H:%M"),
        "maxDays": HIST_DAYS,
        "minAmt": MIN_AMT,
        "stocks": stocks,
        "buy": buy[:TOP_N],
        "sell": sell[:TOP_N],
    })
    print("완료", today, len(stocks), "종목")


if __name__ == "__main__":
    main()
