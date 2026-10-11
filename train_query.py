#!/usr/bin/env python3
"""12306 直达车次查询。仅使用 Python 3.9+ 标准库，不提供购票功能。"""
 
import argparse
import difflib
import http.cookiejar
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
 
BASE_URL = "https://kyfw.12306.cn/otn/"
CHINA_TZ = timezone(timedelta(hours=8))
SEAT_FIELDS = {"商务/特等座": 32, "一等座": 31, "二等座": 30,
               "高级软卧": 21, "软卧": 23, "动卧": 33,
               "硬卧": 28, "硬座": 29, "无座": 26}
 
class QueryError(Exception):
    """可直接展示给用户的查询错误。"""
 
 
def validate_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise QueryError("日期格式必须为 YYYY-MM-DD，例如 2026-10-10。")
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise QueryError("日期不存在，请检查年月日。") from exc
    if day < datetime.now(CHINA_TZ).date():
        raise QueryError("不能查询过去日期的余票，请输入今天或之后的日期。")
    return day
 
 
def parse_stations(text):
    stations = {}
    for record in text.split("@")[1:]:
        fields = record.split("|")
        if len(fields) >= 3 and re.fullmatch(r"[A-Z]{3}", fields[2]):
            stations[fields[1]] = fields[2]
    if not stations:
        raise QueryError("无法解析官方站点表，可能是网络拦截或网站格式已变更。")
    return stations
 
 
def resolve_station(value, stations):
    name = value.strip()
    if name in stations:
        return stations[name]
    if name.endswith("站") and name[:-1] in stations:
        return stations[name[:-1]]
    code = name.upper()
    if code in stations.values():
        return code
    candidates = [item for item in stations if name and name in item][:8]
    if not candidates:
        candidates = difflib.get_close_matches(name, stations, n=5, cutoff=0.4)
    hint = "；可尝试：" + "、".join(candidates) if candidates else ""
    raise QueryError(f"未找到车站：{value}{hint}。请使用官方站名或三字母电报码。")
 
 
def parse_trains(data, station_names, origin_code=None, destination_code=None):
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise QueryError("查询响应缺少车次列表，可能需要人工验证或接口已变更。")
    names = dict(station_names)
    mapping = data.get("map", {})
    if not isinstance(mapping, dict):
        raise QueryError("查询响应中的站名映射格式异常。")
    names.update(mapping)
    trains = []
    for record in data["result"]:
        if not isinstance(record, str):
            raise QueryError("车次数据格式异常。")
        fields = record.split("|")
        if len(fields) < 34:
            raise QueryError("车次字段不足，官方接口格式可能已变更。")
        if origin_code is not None and fields[6] != origin_code:
            continue
        if destination_code is not None and fields[7] != destination_code:
            continue
        trains.append({
            "车次": fields[3],
            "列车始发站": names.get(fields[4], fields[4]),
            "列车终到站": names.get(fields[5], fields[5]),
            "出发站": names.get(fields[6], fields[6]),
            "到达站": names.get(fields[7], fields[7]),
            "出发时间": fields[8],
            "到达时间": fields[9],
            "历时": fields[10],
            "可预订": fields[11] == "Y",
            "状态": fields[1] or ("可预订" if fields[11] == "Y" else "不可预订"),
            "余票": {seat: fields[index] or "--" for seat, index in SEAT_FIELDS.items()},
        })
    return trains
 
 
def validate_filters(only_available, train_type):
    if not isinstance(only_available, bool):
        raise QueryError("ONLY_AVAILABLE 必须为 True 或 False。")
    if train_type not in ("高铁/动车", "普速", "全部"):
        raise QueryError('TRAIN_TYPE 必须为 "高铁/动车"、"普速" 或 "全部"。')
 
 
def filter_trains(trains, only_available=False, train_type="全部"):
    validate_filters(only_available, train_type)
    filtered = []
    for train in trains:
        is_fast = train["车次"].upper().startswith(("G", "D", "C"))
        if train_type == "高铁/动车" and not is_fast:
            continue
        if train_type == "普速" and is_fast:
            continue
        if only_available:
            # “有”或正整数代表余票；无、候补、0、-- 均不算有票。
            seats = (str(value).strip() for value in train["余票"].values())
            has_seat = any(value == "有" or (
                re.fullmatch(r"[0-9]+", value) and int(value) > 0
            ) for value in seats)
            if not train["可预订"] or not has_seat:
                continue
        filtered.append(train)
    return filtered
 
 
class TrainClient:
    def __init__(self, timeout=20):
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
 
    def get(self, path, params=None):
        url = BASE_URL + path
        if params:
            url += "?" + urlencode(params)
        request = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; TrainQuery/1.0)",
            "Referer": BASE_URL + "leftTicket/init",
            "Accept": "application/json, text/javascript, text/html, */*",
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8-sig")
        except HTTPError as exc:
            raise QueryError(f"12306 返回 HTTP {exc.code}，请稍后重试或使用官网查询。") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise QueryError(f"无法连接 12306：{exc}。请检查网络和系统证书。") from exc
        except UnicodeError as exc:
            raise QueryError("响应不是有效的 UTF-8 文本，可能受到网络拦截。") from exc
 
    def query(self, origin, destination, travel_date, exact_stations=False,
              only_available=False, train_type="全部"):
        validate_filters(only_available, train_type)
        day = validate_date(travel_date)
        stations = parse_stations(self.get("resources/js/framework/station_name.js"))
        origin_code = resolve_station(origin, stations)
        destination_code = resolve_station(destination, stations)
        if origin_code == destination_code:
            raise QueryError("出发站和到达站不能相同。")
        names = {code: name for name, code in stations.items()}
        page = self.get("leftTicket/init")
        match = re.search(r"CLeftTicketUrl\s*=\s*['\"](leftTicket/query[A-Za-z]*)['\"]", page)
        if not match:
            raise QueryError("无法从官网获取查询入口，请在官网完成可能的人工验证后重试。")
        endpoint = match.group(1)
        params = {
            "leftTicketDTO.train_date": day.isoformat(),
            "leftTicketDTO.from_station": origin_code,
            "leftTicketDTO.to_station": destination_code,
            "purpose_codes": "ADULT",
        }
        # 仅接受官方响应指定的同站查询路径，最多切换一次；不自动循环重试。
        for attempt in range(2):
            text = self.get(endpoint, params)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise QueryError("12306 未返回 JSON，可能触发访问限制或人工验证，请使用官网查询。") from exc
            if not isinstance(payload, dict):
                raise QueryError("12306 响应格式异常。")
            next_path = payload.get("c_url")
            if (attempt == 0 and isinstance(next_path, str)
                    and re.fullmatch(r"leftTicket/query[A-Za-z]*", next_path)
                    and next_path != endpoint):
                endpoint = next_path
                continue
            if payload.get("status") is not True:
                messages = payload.get("messages") or "服务暂不可用，或日期不在预售期内"
                raise QueryError(f"12306 查询失败：{messages}")
            data = payload.get("data")
            trains = parse_trains(
                data, names,
                origin_code if exact_stations else None,
                destination_code if exact_stations else None,
            )
            return {
                "日期": day.isoformat(),
                "出发站": names[origin_code],
                "到达站": names[destination_code],
                "精确站点": exact_stations,
                "原始记录数": len(data["result"]),
                "站点匹配记录数": len(trains),
                "只看有票": only_available,
                "车型筛选": train_type,
                "车次": filter_trains(trains, only_available, train_type),
            }
        raise QueryError("官方查询入口切换失败，请稍后重试。")
 
 
def display_width(text):
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)
 
 
def print_result(result):
    print(f"{result['日期']}  {result['出发站']} → {result['到达站']}")
    exact = result.get("精确站点", False)
    print("查询范围：仅指定车站。" if exact else
          "查询范围：包含官网返回的同城车站，请以每行的实际出发站、到达站为准。")
    availability = "只看有票（含无座，不含候补）" if result.get("只看有票", False) else "不限余票"
    print(f"筛选条件：{result.get('车型筛选', '全部')}；{availability}。")
    trains = result["车次"]
    if not trains:
        if result.get("站点匹配记录数", 0):
            print("该区间有车次，但没有符合当前余票或车型筛选条件的记录。")
        elif exact and result.get("原始记录数", 0):
            print(f"官网返回 {result['原始记录数']} 条同城乘车区间记录，但没有匹配指定两站的记录。")
            print("可将 EXACT_STATIONS 改为 False，或修改配置中的具体车站。")
        else:
            print("未查询到直达车次，可能尚未开售、超出预售期或当日没有直达列车。")
        return
    headers = ["车次", "出发站", "到达站", "出发时间", "到达时间", "历时"]
    seats = list(SEAT_FIELDS)
    rows = [headers + seats + ["状态"]]
    for train in trains:
        rows.append([train[key] for key in headers]
                    + [train["余票"][seat] for seat in seats] + [train["状态"]])
    widths = [max(display_width(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(value + " " * (widths[i] - display_width(value))
                        for i, value in enumerate(row)))
    print(f"共 {len(trains)} 条乘车区间记录，涉及 {len({train['车次'] for train in trains})} 个车次；")
    print("同一车次可能对应多个上下车站组合；-- 表示未提供该席别余票，不等于有票。")
    print("到达时间可能为次日或更晚，请结合历时判断；余票和售票状态以官网为准。")
 
 
def main():
    """12306 直达车次查询命令行入口。"""
    parser = argparse.ArgumentParser(
        description="查询 12306 两个车站之间的直达车次及余票。",
    )
    parser.add_argument("start_station", help="出发站，支持官方站名或三字母电报码")
    parser.add_argument("end_station", help="到达站，支持官方站名或三字母电报码")
    parser.add_argument("date", help="查询日期，格式为 YYYY-MM-DD")
    parser.add_argument(
        "--exact",
        action="store_true",
        help="仅保留出发站和到达站都与指定站名完全一致的乘车区间",
    )
    parser.add_argument(
        "--only-available",
        action="store_true",
        help="只看有票车次（含无座，不含候补）",
    )
    parser.add_argument(
        "--type",
        default="全部",
        choices=("高铁/动车", "普速", "全部"),
        help="筛选车型：高铁/动车、普速、全部",
    )
    args = parser.parse_args()
    try:
        result = TrainClient().query(
            args.start_station,
            args.end_station,
            args.date,
            exact_stations=args.exact,
            only_available=args.only_available,
            train_type=args.type,
        )
        print_result(result)
        return 0
    except QueryError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\n查询已取消。", file=sys.stderr)
        return 130
 
 
if __name__ == "__main__":
    sys.exit(main())