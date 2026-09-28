#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华南农业大学教务系统课表 -> ICS 日历文件（默认 jwzf 正方版）

用法：
    python scau_ics.py fetch --source jwzf    # jwzf 正方版（默认）
    python scau_ics.py fetch --source jwxt    # jwxt 新版
    python scau_ics.py serve                  # 打开网页版
    python scau_ics.py convert --calendar-json calendar.json --timetable-json timetable.json

只使用 Python 标准库，无需安装第三方依赖。
"""

import argparse
import base64
import datetime as dt
import getpass
import html
import http.cookiejar
import http.server
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser


BASE = "https://jwxt.scau.edu.cn"
OLD_BASE = "https://jwzf.scau.edu.cn"
OLD_PATH = "/jwglxt"
LOGIN_PAGE = BASE + "/Njw2017/login.html"
SEC_SERVICE = BASE + "/secService"
API_LIST_URL = BASE + "/resService/data/api.json"
CAPTCHA_HEADER = "securityKaptchaRedisServiceAdapter"
OLD_LOGIN_PAGE = OLD_BASE + OLD_PATH + "/xtgl/index_initMenu.html?jsdm=xs"
OLD_PUBLIC_KEY_URL = OLD_BASE + OLD_PATH + "/xtgl/login_getPublicKey.html"
OLD_LOGIN_URL = OLD_BASE + OLD_PATH + "/xtgl/login_slogin.html"
OLD_TIMETABLE_URL = OLD_BASE + OLD_PATH + "/kbcx/xskbcx_cxXsgrkb.html?gnmkdm=N2151"

# 学生账号统一身份认证（融合门户 CAS）登录 jwzf 的参数
CAS_BASE = "https://cas.scau.edu.cn"
CAS_TICKETS_URL = CAS_BASE + "/lyuapServer/v1/tickets"
JWZF_SSO_URL = OLD_BASE + "/sso/lyiotlogin"
CAS_MODULUS = (
    "00b5eeb166e069920e80bebd1fea4829d3d1f3216f2aabe79b6c47a3c18dcee5f"
    "d22c2e7ac519cab59198ece036dcf289ea8201e2a0b9ded307f8fb704136eaeb6"
    "70286f5ad44e691005ba9ea5af04ada5367cd724b5a26fdb5120cc95b6431604b"
    "d219c6b7d83a6f8f24b43918ea988a76f93c333aa5a20991493d4eb1117e7b1"
)
CAS_EXPONENT = "010001"

# 2026-2027 学年官方作息时间表（每节 40 分钟）
OLD_SECTION_TIMES = [
    ("08:00", "08:40"),
    ("08:45", "09:25"),
    ("09:55", "10:35"),
    ("10:40", "11:20"),
    ("11:25", "12:05"),
    ("12:40", "13:20"),
    ("13:25", "14:05"),
    ("14:30", "15:10"),
    ("15:15", "15:55"),
    ("16:25", "17:05"),
    ("17:10", "17:50"),
    ("17:55", "18:35"),
    ("19:30", "20:10"),
    ("20:15", "20:55"),
    ("21:00", "21:40"),
]

CALENDAR_KEYWORDS = ("findWeekCalendarList",)
TIMETABLE_KEYWORDS = ("searchOneXskbList",)

# 公开 API 清单里的候选键，作为自动发现失败时的兜底
FALLBACK_CALENDAR_KEYS = (
    "XSMH0701_jw.xsd.xsdInfo.controller.XsdQxxkbController.findWeekCalendarList",
    "XSMH1701_jw.xsd.xsdInfo.controller.xsdpublic.findWeekCalendarList",
    "JCZY0115_jw.jczy.educationinfo.controller.WeekCalendarInfoController.findWeekCalendarList",
)
FALLBACK_TIMETABLE_KEYS = (
    "XSMH0701_jw.xsd.xsdInfo.controller.XsdQxxkbController.searchOneXskbList",
    "XSMH1306_jw.xsd.xsdInfo.controller.MinorCurriculumController.searchOneXskbList",
)
FALLBACK_CALENDAR_URLS = (
    "/jwxtpt/v1/xsd/xjgl_public/findWeekCalendarList"
    "?resourceCode=XSMH1701&apiCode=jw.xsd.xsdInfo.controller.xsdpublic.findWeekCalendarList",
)
FALLBACK_TIMETABLE_URLS = (
    "/jwxtpt/v1/xsd/xsdqxxkb_info/searchOneXskbList"
    "?resourceCode=XSMH0701&apiCode=jw.xsd.xsdInfo.controller.XsdQxxkbController.searchOneXskbList",
)

BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
    "app": "PCWEB",
    "locale": "zh_CN",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}


class ScraperError(Exception):
    """带中文提示的错误。"""


class ApiCallError(ScraperError):
    def __init__(self, message, last_body=None):
        super().__init__(message)
        self.last_body = last_body


def _ssl_context():
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()


def new_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=_ssl_context()),
    )
    return opener


def _headers(extra=None):
    headers = dict(BASE_HEADERS)
    if extra:
        headers.update(extra)
    return headers


def _request(opener, url, method="GET", body=None, headers=None, timeout=25, form=None):
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "certificate" in reason.lower():
            # 个别校园网络证书链不完整时降级重试
            opener2 = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl._create_unverified_context())
            )
            with opener2.open(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        raise ScraperError(f"网络请求失败：{reason}")


def get_json(opener, url, headers=None):
    status, raw = _request(opener, url, method="GET", headers=headers or _headers())
    if status >= 400 and status not in (401, 403):
        raise ScraperError(f"请求失败（HTTP {status}）：{url}")
    return _parse_json(raw, url)


def post_json(opener, url, body, headers=None):
    status, raw = _request(
        opener,
        url,
        method="POST",
        body=body,
        headers=headers or _headers({"Content-Type": "application/json"}),
    )
    if status >= 400 and status not in (401, 403):
        raise ScraperError(f"请求失败（HTTP {status}）：{url}")
    return _parse_json(raw, url)


def post_form(opener, url, fields, headers=None):
    status, raw = _request(
        opener,
        url,
        method="POST",
        form=fields,
        headers=headers or _headers({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}),
    )
    if status >= 400 and status not in (401, 403):
        raise ScraperError(f"请求失败（HTTP {status}）：{url}")
    return status, raw


def _rsa_encrypt(password, modulus_b64, exponent_b64):
    n = int.from_bytes(base64.b64decode(modulus_b64), "big")
    e = int.from_bytes(base64.b64decode(exponent_b64), "big")
    raw = password.encode("utf-8")
    size = (n.bit_length() + 7) // 8
    if len(raw) > size - 11:
        raise ScraperError("密码过长，无法登录")
    padded = b"\x00\x01" + b"\xff" * (size - 3 - len(raw)) + b"\x00" + raw
    encrypted = pow(int.from_bytes(padded, "big"), e, n)
    return base64.b64encode(encrypted.to_bytes(size, "big")).decode("ascii")


def _cas_rsa_encrypt(password):
    """按融合门户前端算法加密密码（16 位小端分组 + 十六进制输出）。"""
    n = int(CAS_MODULUS, 16)
    e = int(CAS_EXPONENT, 16)
    chunk_size = 128
    data = bytearray(password.encode("utf-8"))
    while len(data) % chunk_size:
        data.append(0)
    blocks = []
    for offset in range(0, len(data), chunk_size):
        num = 0
        for i in range(chunk_size // 2):
            word = data[offset + 2 * i] + (data[offset + 2 * i + 1] << 8)
            num |= word << (16 * i)
        blocks.append(format(pow(num, e, n), "x").rjust(256, "0"))
    return " ".join(blocks)


def login_cas(opener, username, password):
    """通过学校统一身份认证自动登录 jwzf，在校学生必须走这条路径。"""
    fields = {
        "username": username.strip(),
        "password": _cas_rsa_encrypt(password),
        "service": JWZF_SSO_URL,
        "loginType": "",
        "id": "",
        "code": "",
        "otpcode": "",
    }
    status, raw = post_form(
        opener,
        CAS_TICKETS_URL,
        fields,
        headers=_headers({
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": CAS_BASE,
        }),
    )
    if status != 200:
        raise ScraperError(f"统一认证登录失败（HTTP {status}），请稍后再试")
    body = _parse_json(raw, CAS_TICKETS_URL)
    if not isinstance(body, dict):
        raise ScraperError("统一认证登录响应格式异常")
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    if meta.get("success") is False:
        message = meta.get("message") or "账号或密码错误"
        raise ScraperError(f"统一认证登录失败：{message}")
    ticket = body.get("ticket")
    if not ticket:
        raise ScraperError("统一认证登录响应中没有票据，请检查账号密码")
    status, raw = _request(
        opener,
        JWZF_SSO_URL + "?ticket=" + urllib.parse.quote(ticket),
        method="GET",
        headers=_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }),
    )
    if status != 200:
        raise ScraperError(f"教务系统 SSO 登录失败（HTTP {status}）")
    page = raw.decode("utf-8", errors="replace")
    if "login_slogin" in page:
        raise ScraperError("统一认证登录后教务系统仍要求重新登录，请稍后再试")
    return True


def login_jwzf(opener, username, password, captcha=None):
    """学生优先使用统一认证；个别账号（如结业学生）失败时退回普通登录。"""
    try:
        return login_cas(opener, username, password)
    except ScraperError as cas_error:
        try:
            return login_old(opener, username, password, captcha)
        except ScraperError:
            raise cas_error


def login_old(opener, username, password, captcha=None):
    """登录 jwzf 正方教务系统（V9 版），成功后 opener 携带登录 Cookie。"""
    headers = _headers({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    status, raw = _request(opener, OLD_LOGIN_PAGE, method="GET", headers=headers)
    if status != 200:
        raise ScraperError(f"教务系统登录页打开失败（HTTP {status}）")
    page = raw.decode("utf-8", errors="replace")
    m = re.search(r'name="csrftoken"\s+value="([^"]+)"', page)
    if not m:
        raise ScraperError("登录页没有找到 csrftoken，教务系统可能已改版")
    csrf = m.group(1)

    key = get_json(
        opener,
        OLD_PUBLIC_KEY_URL + "?time=" + str(int(time.time() * 1000)),
        headers=_headers({"X-Requested-With": "XMLHttpRequest"}),
    )
    encrypted = _rsa_encrypt(password, key.get("modulus") or "", key.get("exponent") or "")
    fields = [
        ("csrftoken", csrf),
        ("language", "zh_CN"),
        ("yhm", username.strip()),
        ("mm", encrypted),
        ("mm", encrypted),
        ("ydType", ""),
    ]
    if captcha:
        fields.append(("yzm", captcha))
    status, raw = post_form(
        opener,
        OLD_LOGIN_URL + "?time=" + str(int(time.time() * 1000)),
        fields,
        headers=_headers({"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}),
    )
    page = raw.decode("utf-8", errors="replace")
    if "用户名或密码不正确" in page:
        raise ScraperError("账号或密码错误，请检查 jwzf 教务系统的学号和密码")
    if "用户不存在" in page or "用户不存在！" in page:
        raise ScraperError("该账号在 jwzf 教务系统中不存在")
    if "验证码" in page and "yzm" in page:
        raise ScraperError("jwzf 登录需要验证码，请在命令行加 --captcha 后重试")
    if 'name="yhm"' in page and "login_slogin" in page:
        raise ScraperError("jwzf 登录失败，请检查账号密码或稍后再试")
    return True


def _parse_json(raw, url):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except ValueError:
        raise ScraperError(f"接口返回的不是 JSON：{url}\n返回内容前 200 字符：{text[:200]}")


def auth_headers(token, extra=None):
    headers = _headers({
        "TOKEN": token or "",
        "userRoleCode": "",
        "Simulated-By": "",
    })
    if extra:
        headers.update(extra)
    return headers


def _captcha_check_url():
    return SEC_SERVICE + "/kaptcha/check/must.json?resourceCode=resourceCode&t=" + str(int(time.time() * 1000))


def captcha_required(opener):
    headers = _headers({"KAPTCHA-KEY-GENERATOR-REDIS": CAPTCHA_HEADER})
    body = get_json(opener, _captcha_check_url(), headers=headers)
    value = body.get("data") if isinstance(body, dict) else body
    return bool(value)


def captcha_image(opener):
    url = SEC_SERVICE + "/kaptcha?t=" + str(int(time.time() * 1000)) + \
          "&KAPTCHA-KEY-GENERATOR-REDIS=" + CAPTCHA_HEADER
    status, raw = _request(
        opener,
        url,
        method="GET",
        headers=_headers({"KAPTCHA-KEY-GENERATOR-REDIS": CAPTCHA_HEADER}),
    )
    if status != 200:
        raise ScraperError(f"验证码图片下载失败（HTTP {status}）")
    return raw


def login(opener, username, password, captcha=None):
    """登录教务系统，返回 token。"""
    _request(opener, LOGIN_PAGE, method="GET", headers=_headers())  # 建立会话 Cookie

    need_captcha = captcha_required(opener)
    payload = {
        "userCode": username.strip(),
        "password": password,
        "kaptcha": (captcha or "testa").strip(),
        "userCodeType": "account",
    }
    headers = _headers({
        "Content-Type": "application/json",
        "KAPTCHA-KEY-GENERATOR-REDIS": CAPTCHA_HEADER,
    })
    body = post_json(opener, SEC_SERVICE + "/login", payload, headers=headers)

    if body.get("errorCode") not in (None, "success"):
        if body.get("errorCode") == "security.SysUserService.authLogin.passwd.toUpdate":
            raise ScraperError("首次登录或密码已过期，需要先到教务系统修改密码")
        if body.get("errorCode") == "HTTP_STATUS.429":
            raise ScraperError("登录过于频繁，请稍后再试")
        code = str(body.get("errorCode") or "")
        if "kaptcha" in code.lower():
            raise ScraperError("验证码错误或已过期，请刷新页面重新输入验证码")
        if "401" in code or "passwd" in code.lower():
            raise ScraperError("账号或密码错误，请检查学号、密码是否正确（新生的初始密码一般是身份证后六位）")
        msg = body.get("errorMessage") or body.get("errorMessageParam") or body.get("errorCode")
        if need_captcha and captcha:
            hint = "（若验证码错误，请重新获取验证码再试）"
        else:
            hint = ""
        raise ScraperError(f"登录失败：{msg} {hint}".strip())

    token = body.get("token")
    if not token and isinstance(body.get("data"), dict):
        token = body["data"].get("token")
    if not token:
        raise ScraperError("登录响应中没有 token，教务系统可能已改版")
    return token


def fetch_api_map(opener, token):
    """获取当前账号可用的 API 清单。"""
    body = get_json(opener, API_LIST_URL, headers=auth_headers(token))
    data = body.get("data") if isinstance(body, dict) else body
    if not isinstance(data, dict):
        raise ScraperError("API 清单格式异常")
    return data


def find_api_key(api_map, keywords, prefer_substrings=()):
    matches = [k for k in api_map if any(w in k for w in keywords)]
    if not matches:
        return None
    for pref in prefer_substrings:
        for key in matches:
            if pref in key:
                return key
    return matches[0]


def build_api_urls(api_value):
    value = str(api_value).replace("{version}", "v1")
    if value.startswith("http"):
        return [value]
    urls = []
    for prefix in (BASE + "/resService", BASE):
        if value.startswith("/"):
            urls.append(prefix + value)
        else:
            urls.append(prefix + "/" + value)
    return list(dict.fromkeys(urls))


def is_http_404(body):
    if not isinstance(body, dict):
        return False
    code = str(body.get("errorCode") or "")
    return "404" in code


def call_api(opener, token, api_value, payloads, check_ok, label):
    errors = []
    last_body = None
    for url in build_api_urls(api_value):
        for payload in payloads:
            try:
                body = post_json(opener, url, payload, headers=auth_headers(token))
            except ScraperError as exc:
                errors.append(f"{url} {payload}: {exc}")
                continue
            last_body = body
            try:
                if check_ok(body):
                    return body
            except Exception as exc:
                errors.append(f"{url} {payload}: 返回格式不符（{exc}）")
                continue
            errors.append(f"{url} {payload}: {body.get('errorMessage') or body.get('errorCode')}")
    raise ApiCallError(
        f"自动获取{label}失败，已尝试 {len(errors)} 种组合。"
        f"\n请使用备用方式（README 中的 convert 模式）或反馈以下信息："
        f"\n" + "\n".join(errors[-5:]) +
        (f"\n\n提示：报错中包含 /jwxtpt 的 HTTP 404 时，说明当前网络访问不到教务系统的课表服务。"
         f"请改用校园网直连，或按 README 的备用模式用浏览器复制 JSON 转换。"
         if any("jwxtpt" in e and ("404" in e or "Not Found" in e) for e in errors) else ""),
        last_body=last_body,
    )


def _week_entries(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        data = body.get("data")
        candidates = [data] if not isinstance(data, list) else [data]
        for val in candidates:
            if isinstance(val, dict):
                for key in ("jxzllist", "xnxqlist", "xnxqList", "list", "items", "rows"):
                    sub = val.get(key)
                    if isinstance(sub, list) and sub:
                        return sub
            elif isinstance(val, list) and val:
                return val
    return []


def semester_start(calendar_body):
    entries = _week_entries(calendar_body)
    if not entries:
        raise ScraperError("校历接口返回中没有学期列表（jxzllist）字段")
    return entries


def choose_semester(entries, wanted=None):
    for entry in entries:
        label = " ".join(str(entry.get(k) or "") for k in ("xnxq", "name", "xnxqmc"))
        if wanted and wanted.strip() in label:
            return entry
    if not wanted:
        # 默认取第 0 个（教务系统通常把当前学期放在最前）
        return entries[0]
    raise ScraperError(f"没有找到学期 {wanted}，可用的学期有："
                       + "、".join(str(e.get("xnxq") or e.get("name")) for e in entries))


def parse_xnxq(xnxq):
    m = re.match(r"\s*(\d{4})-(\d{4})-(\d+)\s*", str(xnxq))
    if m:
        return m.group(1) + "-" + m.group(2), m.group(3)
    m = re.match(r"\s*(\d{4})-(\d{4})\s*[学年第]*\s*(\d+)", str(xnxq))
    if m:
        return m.group(1) + "-" + m.group(2), m.group(3)
    return None, None


def timetable_payloads(entry):
    xnm, xqm = parse_xnxq(entry.get("xnxq") or "")
    candidates = [{}]
    if xnm and xqm:
        candidates.extend([
            {"xnm": xnm, "xqm": xqm},
            {"xnm": xnm, "xqm": xqm, "kzlx": "xs"},
            {"xnm": xnm, "xqm": xqm, "kzlx": ""},
            {"xnm": xnm, "xqm": xqm, "xnxq": entry.get("xnxq")},
            {"xnxq": entry.get("xnxq")},
            {"xnm": xnm.split("-")[0], "xqm": xqm},
            {"xnm": xnm.split("-")[0], "xqm": {"1": "3", "2": "12", "3": "16"}.get(xqm, xqm)},
        ])
    return candidates


def calendar_payloads():
    today = dt.date.today()
    year = today.year
    fall = year if today.month >= 9 else year - 1
    return [
        {},
        {"xnm": f"{fall}-{fall + 1}", "xqm": "1"},
        {"xnm": f"{fall}-{fall + 1}", "xqm": "2"},
        {"xnm": f"{fall - 1}-{fall}", "xqm": "3"},
        {"xnm": str(fall), "xqm": "3"},
    ]


def _to_hm(value):
    if value is None:
        return "00:00"
    s = str(value).strip()
    if ":" in s:
        parts = s.split(":")
        hh = parts[0].zfill(2)
        mm = (parts[1] if len(parts) > 1 else "00").zfill(2)
        return hh + ":" + mm
    if len(s) == 3:
        s = "0" + s
    if len(s) == 4 and s.isdigit():
        return s[:2] + ":" + s[2:]
    return "00:00"


def extract_courses(timetable_body):
    if isinstance(timetable_body, list):
        courses = timetable_body
    elif isinstance(timetable_body, dict):
        data = timetable_body.get("data")
        if isinstance(data, list):
            courses = data
        elif isinstance(data, dict):
            courses = None
            for key in ("list", "items", "rows", "xskbList", "kbList", "resultList"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    courses = val
                    break
        else:
            courses = None
    else:
        courses = None
    if not courses:
        raise ScraperError("课表接口返回中没有课程数据")
    if not isinstance(courses[0], dict) or "kc_name" not in courses[0]:
        raise ScraperError("课表接口返回的课程格式与预期不符，请使用备用转换模式")
    return courses


def _text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value).strip()


def _class_title(course):
    title = _text(course.get("kc_name"))
    if str(course.get("arrange_num") or "1") != "1":
        title += "(" + _text(course.get("xslx_name1")) + ")"
    fzmc = _text(course.get("fzmc_name"))
    if fzmc:
        title += "[" + fzmc + "]"
    return title or "未命名课程"


def _description(course, week):
    teacher = _text(course.get("teachernames"))
    ktmc = _text(course.get("ktmc_name"))
    parts = [f"第{week}周"]
    if teacher:
        parts.append(teacher)
    if ktmc:
        parts.append(ktmc)
    return " | ".join(parts)


def _weeks(course):
    raw = str(course.get("pkzc_1") or course.get("pkzc") or "")
    if not raw:
        return []
    weeks = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                weeks.append((int(start), int(end)))
            except ValueError:
                continue
        else:
            try:
                weeks.append((int(part), int(part)))
            except ValueError:
                continue
    return weeks


def _week_filter(course):
    code = str(course.get("sjbzcode") or "1")
    if code == "2":  # 单周
        return lambda w: w % 2 == 1
    if code == "3":  # 双周
        return lambda w: w % 2 == 0
    return lambda w: True


def _ics_escape(value):
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    value = value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return value


def _parse_weekday(pksj):
    text = str(pksj or "").strip()
    if not text:
        return None
    # 形如 "周一第1,2节" / "星期六第1节" / "星期一"
    if text.startswith(("周", "星期")):
        zh_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
        for ch in text[1:]:
            if ch in zh_map:
                return zh_map[ch]
    # 形如 "1第1,2节" 或 "3"
    m = re.match(r"\s*([1-7])", text)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-7])", text)
    return int(m.group(1)) if m else None


def _old_week_ranges(raw):
    """把 zcd 字段（如 1-16周(单)）转成 (起, 止, 单双代码) 列表。"""
    text = str(raw or "").replace("周", "").strip()
    result = []
    for part in re.split(r"[,，;；]", text):
        part = part.strip()
        if not part:
            continue
        code = 1
        pm = re.match(r"^(.+?)[（(](单|双)[）)]$", part)
        if pm:
            part = pm.group(1)
            code = 2 if pm.group(2) == "单" else 3
        m = re.match(r"^(\d+)-(\d+)$", part)
        if m:
            result.append((int(m.group(1)), int(m.group(2)), code))
        elif re.match(r"^\d+$", part):
            w = int(part)
            result.append((w, w, code))
    return result


def _old_section_numbers(jc):
    text = str(jc or "").replace("节", "").strip()
    m = re.match(r"^(\d+)\s*[-—~至到]\s*(\d+)$", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    n = int(text) if re.match(r"^\d+$", text) else 1
    return n, n


def _old_section_time(jc, end=False):
    first, last = _old_section_numbers(jc)
    first, last = min(first, last), max(first, last)
    start = OLD_SECTION_TIMES[first - 1][0] if 0 < first <= len(OLD_SECTION_TIMES) else "08:00"
    stop = OLD_SECTION_TIMES[last - 1][1] if 0 < last <= len(OLD_SECTION_TIMES) else "21:40"
    return stop if end else start


def _normalize_old_course(course):
    ranges = _old_week_ranges(course.get("zcd"))
    if not ranges:
        week_text = ""
        week_code = "1"
    elif len({code for _, _, code in ranges}) == 1:
        week_text = ",".join(f"{s}-{e}" for s, e, _ in ranges)
        week_code = str(ranges[0][2])
    else:
        weeks = []
        for s, e, code in ranges:
            for w in range(s, e + 1):
                if code == 2 and w % 2 == 0:
                    continue
                if code == 3 and w % 2 == 1:
                    continue
                weeks.append(str(w))
        week_text = ",".join(weeks)
        week_code = "1"
    return {
        "id": course.get("jxb_id") or course.get("kch_id")
        or f"{course.get('kcmc')}_{course.get('xqj')}_{course.get('zcd')}_{course.get('jc')}",
        "kc_name": course.get("kcmc") or "未命名课程",
        "fzmc_name": course.get("fzmc_name") or course.get("kcxzmc") or "",
        "arrange_num": "1",
        "xslx_name1": course.get("kcxz") or "",
        "pkzc_1": week_text,
        "sjbzcode": week_code,
        "pksj": course.get("xqjmc") or course.get("xqj"),
        "djkssj": _old_section_time(course.get("jc"), False),
        "djjssj": _old_section_time(course.get("jc"), True),
        "teachernames": course.get("xm") or "",
        "ktmc_name": course.get("xm") or "",
        "js_name_1": course.get("cdmc") or "",
    }


def _old_xnxq(semester):
    if semester:
        m = re.match(r"^\s*(\d{4})-(\d{4})-\s*(\d+)\s*$", semester)
        if m:
            term_code = {"1": "3", "2": "12", "3": "16"}.get(m.group(3), m.group(3))
            return m.group(1), term_code
        m = re.match(r"^\s*(\d{4})[-年]?\s*(\d+)\s*$", semester)
        if m:
            return m.group(1), m.group(2)
    today = dt.date.today()
    if today.month >= 8:
        return str(today.year), "3"
    if today.month >= 2:
        return str(today.year - 1), "12"
    return str(today.year - 1), "3"


def _default_old_start(xnm, xqm):
    today = dt.date.today()
    if xqm in ("3", "1"):
        default = dt.date(int(xnm), 9, 1)
    elif xqm in ("12", "2"):
        default = dt.date(int(xnm) + 1, 2, 24)
    else:
        default = dt.date(int(xnm) + 1, 7, 6)
    return default + dt.timedelta(days=(0 - default.weekday()))


def _resolve_old_start(start_date, xnm, xqm):
    if start_date:
        try:
            return dt.datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise ScraperError("开学日期格式不对，请用 2026-09-01 这样的格式")
    default = _default_old_start(xnm, xqm)
    print(f"已自动使用本学期第 1 周周一日期：{default.isoformat()}")
    return default


def old_fetch_timetable(opener, xnm, xqm, debug=False):
    fields = {
        "xnm": str(xnm),
        "xqm": str(xqm),
        "kzlx": "ck",
        "xsdm": "",
        "kclbdm": "",
        "kclxdm": "",
    }
    status, raw = post_form(
        opener,
        OLD_TIMETABLE_URL,
        fields,
        headers=_headers({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": OLD_BASE + OLD_PATH + "/kbcx/xskbcx_cxXskbcxIndex.html?gnmkdm=N2151&layout=default",
        }),
    )
    if status != 200:
        raise ScraperError(f"课表请求失败（HTTP {status}）")
    text = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(text)
    except ValueError:
        raise ScraperError("jwzf 课表接口返回的不是 JSON")
    kb_list = body.get("kbList") if isinstance(body, dict) else None
    if not isinstance(kb_list, list) or not kb_list:
        raise ScraperError("jwzf 课表接口返回中没有课程数据")
    if debug:
        with open("timetable_old.json", "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        print("已保存 timetable_old.json")
    return kb_list


def _old_label(xnm, xqm):
    year = int(xnm)
    if str(xqm) in ("3", "1"):
        return f"{year}-{year + 1}-1"
    if str(xqm) in ("12", "2"):
        return f"{year}-{year + 1}-2"
    if str(xqm) in ("16",):
        return f"{year}-{year + 1}-3"
    return f"{xnm}-{xqm}"


def fetch_and_build_old(opener, username, semester=None, start_date=None, debug=False):
    xnm, xqm = _old_xnxq(semester)
    kb_list = old_fetch_timetable(opener, xnm, xqm, debug=debug)
    courses = [_normalize_old_course(item) for item in kb_list if isinstance(item, dict)]
    if not courses:
        raise ScraperError("jwzf 课表中没有可导出的课程")
    start = _resolve_old_start(start_date, xnm, xqm)
    label = _old_label(xnm, xqm)
    entry = {"rq": start.strftime("%Y-%m-%d"), "xnxq": label}
    ics = build_ics(courses, entry, calendar_name=f"{label}课表")
    return ics, label, len(courses)


def _fold(line):
    out = []
    while len(line) > 75:
        out.append(line[:75])
        line = " " + line[75:]
    out.append(line)
    return "\r\n".join(out)


def build_ics(courses, semester_entry, calendar_name="华南农业大学课表"):
    rq = semester_entry.get("rq") or semester_entry.get("ksrq")
    try:
        rq = int(rq)
    except (TypeError, ValueError):
        if isinstance(rq, str) and rq.strip():
            semester_start_date = None
            for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    semester_start_date = dt.datetime.strptime(rq.strip(), fmt).date()
                    break
                except ValueError:
                    continue
            if semester_start_date is None:
                raise ScraperError("校历中的开学时间字段（rq）无法解析：" + str(rq))
        else:
            raise ScraperError("校历中的开学时间字段（rq）缺失")
    else:
        if rq > 10_000_000_000:  # 毫秒时间戳
            rq = rq / 1000
        semester_start_date = dt.datetime.fromtimestamp(rq).date()

    events = []
    uid_base = 0
    for course in courses:
        title = _class_title(course)
        location = _text(course.get("js_name_1") or course.get("js_name"))
        week_day = _parse_weekday(course.get("pksj"))
        if not week_day:
            raise ScraperError(f"课程 {title} 的上课时间格式无法解析：{course.get('pksj')}")
        start_hm = _to_hm(course.get("djkssj") or course.get("idjkssj"))
        end_hm = _to_hm(course.get("djjssj") or course.get("idjjssj"))
        keep_week = _week_filter(course)

        for start_w, end_w in _weeks(course):
            for week in range(start_w, end_w + 1):
                if not keep_week(week):
                    continue
                day = semester_start_date + dt.timedelta(weeks=week - 1, days=week_day - 1)
                start_dt = dt.datetime.combine(day, dt.datetime.strptime(start_hm, "%H:%M").time())
                end_dt = dt.datetime.combine(day, dt.datetime.strptime(end_hm, "%H:%M").time())
                if end_dt <= start_dt:
                    end_dt = start_dt + dt.timedelta(minutes=40)
                uid_base += 1
                events.append({
                    "uid": f"scau-{course.get('id') or uid_base}-{week}-{uid_base}@scau-ics",
                    "start": start_dt,
                    "end": end_dt,
                    "summary": title,
                    "description": _description(course, week),
                    "location": location,
                })

    now = dt.datetime.now()
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//SCAU//Course Schedule by zeta//CN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _ics_escape(calendar_name),
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Shanghai",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append("UID:" + ev["uid"])
        lines.append("DTSTAMP;TZID=Asia/Shanghai:" + now.strftime("%Y%m%dT%H%M%S"))
        lines.append("DTSTART;TZID=Asia/Shanghai:" + ev["start"].strftime("%Y%m%dT%H%M%S"))
        lines.append("DTEND;TZID=Asia/Shanghai:" + ev["end"].strftime("%Y%m%dT%H%M%S"))
        lines.append("SUMMARY:" + _ics_escape(ev["summary"]))
        lines.append("DESCRIPTION:" + _ics_escape(ev["description"]))
        if ev["location"]:
            lines.append("LOCATION:" + _ics_escape(ev["location"]))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip()
    return name or "课表"


def _semester_list(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ("JwPublicXnxq", "list", "items", "rows", "xnxqList"):
            val = body.get(key)
            if isinstance(val, list) and val:
                return val
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("JwPublicXnxq", "list", "items", "rows", "xnxqList"):
                val = data.get(key)
                if isinstance(val, list) and val:
                    return val
        elif isinstance(data, list):
            return data
    return []


def _time_modes(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ("pkgl002List", "list", "items", "rows"):
            val = body.get(key)
            if isinstance(val, list) and val:
                return val
        data = body.get("data")
        if isinstance(data, list):
            return data
    return []


def choose_public_semester(semesters, wanted=None):
    if not semesters:
        raise ScraperError("没有获取到学期列表")
    if wanted:
        for sem in semesters:
            label = " ".join(str(sem.get(k) or "") for k in ("name", "xnxq", "xnxqmc", "id"))
            if wanted.strip() in label:
                return sem
        raise ScraperError(f"没有找到学期 {wanted}，可用的学期有："
                           + "、".join(str(s.get("name") or s.get("xnxq")) for s in semesters))
    for sem in semesters:
        if str(sem.get("sfdqxqcode")) == "1":
            return sem
    return semesters[0]


def fetch_and_build(opener, token, semester=None, debug=False):
    api_map = fetch_api_map(opener, token)
    if debug:
        with open("api_list.json", "w", encoding="utf-8") as f:
            json.dump(api_map, f, ensure_ascii=False, indent=2)
        print("已保存 API 清单：api_list.json")

    def save_debug(name, body):
        if debug:
            with open(name, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False, indent=2)
            print(f"已保存 {name}")

    def find_value(keywords, prefer_substrings=(), fallback_urls=()):
        key = find_api_key(api_map, keywords, prefer_substrings)
        if key:
            return api_map[key]
        if fallback_urls:
            return fallback_urls[0]
        return None

    sem_value = find_value(("JwPublicController.findPublicDic",), ("JCZY0101",))
    tm_value = find_value(("searchPkgl002List",), ("XsdJsjyglController",))
    cal_value = find_value(
        ("findWeekCalendarListHnnydx", "findWeekCalendarList"),
        ("WeekCalendarInfoController",),
        FALLBACK_CALENDAR_URLS,
    )
    kb_value = find_value(
        ("searchOneXskbList",),
        ("XsdQxxkbController",),
        FALLBACK_TIMETABLE_URLS,
    )
    if not kb_value:
        raise ScraperError("没有找到课表接口（searchOneXskbList），请用备用转换模式")

    # 优先使用与教务系统前端一致的调用流程
    if sem_value and tm_value and cal_value:
        try:
            sem_body = call_api(
                opener, token, sem_value, [{"JwPublicXnxq": {}}],
                lambda b: bool(_semester_list(b)), "学期列表",
            )
        except ApiCallError as exc:
            if debug and exc.last_body is not None:
                save_debug("last_semester.json", exc.last_body)
            raise
        semesters = _semester_list(sem_body)
        sem = choose_public_semester(semesters, semester)
        sem_id = str(sem.get("id") or sem.get("jczy013id"))
        sem_name = str(sem.get("name") or sem.get("xnxqmc") or sem.get("xnxq") or "当前学期")
        save_debug("semester.json", sem_body)

        try:
            tm_body = call_api(
                opener, token, tm_value, [{"jczy013id": sem_id}],
                lambda b: bool(_time_modes(b)), "时间模式",
            )
        except ApiCallError as exc:
            if debug and exc.last_body is not None:
                save_debug("last_time_mode.json", exc.last_body)
            raise
        modes = _time_modes(tm_body)
        mode_id = str(modes[0].get("id"))
        save_debug("time_mode.json", tm_body)

        try:
            cal_body = call_api(
                opener, token, cal_value,
                [{"xnxq": sem_id}, {"jczy013id": sem_id}, {}],
                lambda b: bool(_week_entries(b)), "校历",
            )
        except ApiCallError as exc:
            if debug and exc.last_body is not None:
                save_debug("last_calendar.json", exc.last_body)
            raise
        weeks = _week_entries(cal_body)
        start_entry = weeks[0]
        save_debug("calendar.json", cal_body)

        try:
            kb_body = call_api(
                opener, token, kb_value,
                [{"jczy013id": sem_id, "pkgl002id": mode_id, "zt": "2", "sctype": "hnnydx"}],
                lambda b: _courses_ok(b), "课表",
            )
        except ApiCallError as exc:
            if debug and exc.last_body is not None:
                save_debug("last_timetable.json", exc.last_body)
            raise
        courses = extract_courses(kb_body)
        save_debug("timetable.json", kb_body)
        ics = build_ics(courses, start_entry, calendar_name=f"{sem_name}课表")
        return ics, sem_name, len(courses)

    # 旧接口兜底
    try:
        calendar_body = call_api(
            opener, token, cal_value, calendar_payloads(),
            lambda b: bool(semester_start(b)), "校历",
        )
    except ApiCallError as exc:
        if debug and exc.last_body is not None:
            save_debug("last_calendar.json", exc.last_body)
        raise
    entries = semester_start(calendar_body)
    entry = choose_semester(entries, semester)
    save_debug("calendar.json", calendar_body)

    try:
        timetable_body = call_api(
            opener, token, kb_value, timetable_payloads(entry),
            lambda b: _courses_ok(b), "课表",
        )
    except ApiCallError as exc:
        if debug and exc.last_body is not None:
            save_debug("last_timetable.json", exc.last_body)
        raise
    courses = extract_courses(timetable_body)
    save_debug("timetable.json", timetable_body)

    xnxq = str(entry.get("xnxq") or "当前学期")
    ics = build_ics(courses, entry, calendar_name=f"{xnxq}课表")
    return ics, xnxq, len(courses)


def _courses_ok(body):
    try:
        return bool(extract_courses(body))
    except ScraperError:
        return False


def load_json_file(path):
    if not os.path.isfile(path):
        raise ScraperError(f"文件不存在：{path}")
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def convert_command(args):
    timetable_body = load_json_file(args.timetable_json)
    raw_courses = timetable_body.get("kbList") if isinstance(timetable_body, dict) else None
    if isinstance(raw_courses, list) and raw_courses and isinstance(raw_courses[0], dict) and "kcmc" in raw_courses[0]:
        if args.start_date:
            try:
                start = dt.datetime.strptime(args.start_date, "%Y-%m-%d").date()
            except ValueError:
                raise ScraperError("开学日期格式不对，请用 2026-09-01 这样的格式")
        else:
            start_input = input("请输入本学期第 1 周周一日期（例如 2026-09-01）：").strip()
            try:
                start = dt.datetime.strptime(start_input, "%Y-%m-%d").date()
            except ValueError:
                raise ScraperError("开学日期格式不对，请用 2026-09-01 这样的格式")
        courses = [_normalize_old_course(item) for item in raw_courses if isinstance(item, dict)]
        entry = {"rq": start.strftime("%Y-%m-%d")}
        label = str(timetable_body.get("xnxqmc") or "当前学期")
        ics = build_ics(courses, entry, calendar_name=args.name or f"{label}课表")
        return ics, label, len(courses)
    if not args.calendar_json:
        raise ScraperError("转换 jwxt 课表时需要同时提供 --calendar-json；jwzf 课表不需要")
    calendar_body = load_json_file(args.calendar_json)
    entries = semester_start(calendar_body)
    entry = choose_semester(entries, args.semester)
    courses = extract_courses(timetable_body)
    ics = build_ics(courses, entry, calendar_name=args.name or f"{entry.get('xnxq')}课表")
    return ics, str(entry.get("xnxq") or "当前学期"), len(courses)


def write_output(ics, xnxq, count, out_dir, username="课表"):
    os.makedirs(out_dir, exist_ok=True)
    filename = safe_filename(f"{username}_{xnxq}课表.ics")
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    print(f"已生成 {path}")
    print(f"共 {count} 条课程安排")
    return path


def fetch_command(args):
    username = args.username or input("请输入学号：").strip()
    if not username:
        raise ScraperError("学号不能为空")
    password = args.password if args.password is not None else getpass.getpass("请输入密码：")
    source = (args.source or "jwzf").strip().lower()

    if source == "jwzf":
        opener = new_opener()
        login_jwzf(opener, username, password, args.captcha)
        print("登录成功，正在获取课表...")
        ics, xnxq, count = fetch_and_build_old(
            opener, username, semester=args.semester,
            start_date=args.start_date, debug=args.debug,
        )
        path = write_output(ics, xnxq, count, args.out_dir, username)
        print("完成！可以把 .ics 文件导入手机或电脑日历。")
        return path

    opener = new_opener()
    need_captcha = None
    try:
        need_captcha = captcha_required(opener)
    except Exception:
        pass

    captcha = None
    if need_captcha:
        if args.captcha:
            captcha = args.captcha
        else:
            try:
                img = captcha_image(opener)
                with open("captcha.png", "wb") as f:
                    f.write(img)
                print("已生成验证码图片：captcha.png，请打开查看后输入验证码")
            except Exception:
                print("验证码图片下载失败，尝试直接登录（可能不需要验证码）")
            captcha = input("请输入验证码（没有则直接回车）：").strip() or None

    token = login(opener, username, password, captcha)
    print("登录成功，正在获取课表...")
    ics, xnxq, count = fetch_and_build(opener, token, semester=args.semester, debug=args.debug)
    path = write_output(ics, xnxq, count, args.out_dir, username)
    print("完成！可以把 .ics 文件导入手机或电脑日历。")
    return path


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>华农课表导出 ICS · zeta</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #f2f4f7; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: #1f2937;
  }
  .card {
    width: min(420px, 92vw); background: #fff; border-radius: 12px; padding: 28px 26px;
    box-shadow: 0 12px 32px rgba(31, 41, 55, .12);
  }
  h1 { font-size: 20px; margin: 0 0 6px; }
  p.sub { color: #6b7280; font-size: 13px; margin: 0 0 20px; }
  label { display: block; font-size: 13px; margin: 12px 0 6px; color: #374151; }
  input {
    width: 100%; height: 40px; padding: 0 12px; border: 1px solid #d1d5db; border-radius: 8px;
    font-size: 14px; outline: none;
  }
  input:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, .12); }
  select {
    width: 100%; height: 40px; padding: 0 10px; border: 1px solid #d1d5db; border-radius: 8px;
    font-size: 14px; outline: none; background: #fff;
  }
  .row { display: flex; gap: 10px; align-items: center; }
  .row input { flex: 1; }
  .captcha img { height: 44px; border: 1px solid #d1d5db; border-radius: 8px; }
  button {
    width: 100%; height: 42px; margin-top: 20px; border: 0; border-radius: 8px; cursor: pointer;
    background: #2563eb; color: #fff; font-size: 15px;
  }
  button:hover { background: #1d4ed8; }
  .msg { margin-top: 14px; padding: 10px 12px; border-radius: 8px; font-size: 13px; }
  .err { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
  .ok { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
  .tip { color: #9ca3af; font-size: 12px; margin-top: 16px; line-height: 1.6; }
  .credit { color: #9ca3af; font-size: 12px; text-align: center; margin-top: 14px; }
</style>
</head>
<body>
<div class="card">
  <h1>华南农业大学课表转 ICS</h1>
  <p class="sub">输入学号密码，自动生成可导入日历的 .ics 文件</p>
  <form method="post" action="/fetch">
    <label for="source">教务系统</label>
    <select id="source" name="source">
      <option value="jwzf"{source_jwzf_selected}>jwzf 正方教务（推荐）</option>
      <option value="jwxt"{source_jwxt_selected}>jwxt 新教务</option>
    </select>
    <label for="username">学号</label>
    <input id="username" name="username" autocomplete="username" value="{username_attr}" required>
    <label for="password">密码</label>
    <input id="password" name="password" type="password" autocomplete="current-password" value="{password_attr}" required>
    <label for="start_date">本学期第 1 周周一日期（jwzf 用，已自动填好）</label>
    <input id="start_date" name="start_date" type="date" value="{start_date_attr}">
    {captcha_block}
    {session_block}
    <button type="submit">生成课表文件</button>
  </form>
  <div id="msg" class="msg {msg_class}">{msg}</div>
  <div class="tip">账号密码只在本机处理，不会上传到任何第三方服务。若接口改版导致失败，请改用命令行备用模式。</div>
  <div class="credit">本工具由 zeta 制作</div>
</div>
</body>
</html>
"""


def _page_html(session_id=None, msg="", msg_class="", need_captcha=False, username="", password="",
               source="jwzf", start_date=""):
    captcha_block = ""
    session_block = ""
    if not start_date:
        xnm, xqm = _old_xnxq(None)
        start_date = _default_old_start(xnm, xqm).isoformat()
    username_attr = html.escape(username or "", quote=True)
    password_attr = html.escape(password or "", quote=True)
    start_date_attr = html.escape(start_date or "", quote=True)
    source = (source or "jwzf").strip().lower() or "jwzf"
    source_jwzf_selected = " selected" if source == "jwzf" else ""
    source_jwxt_selected = " selected" if source == "jwxt" else ""
    if need_captcha and session_id:
        captcha_block = (
            '<label for="captcha">验证码</label>'
            '<div class="row">'
            '<input id="captcha" name="captcha" autocomplete="off" required>'
            f'<div class="captcha"><img src="/captcha?session={urllib.parse.quote(session_id)}" alt="验证码"></div>'
            "</div>"
        )
    if session_id:
        session_block = f'<input type="hidden" name="session" value="{html.escape(session_id)}">'
    return (
        PAGE.replace("{captcha_block}", captcha_block)
        .replace("{session_block}", session_block)
        .replace("{username_attr}", username_attr)
        .replace("{password_attr}", password_attr)
        .replace("{start_date_attr}", start_date_attr)
        .replace("{source_jwzf_selected}", source_jwzf_selected)
        .replace("{source_jwxt_selected}", source_jwxt_selected)
        .replace("{msg}", html.escape(msg))
        .replace("{msg_class}", msg_class)
    )


class SessionState:
    def __init__(self):
        self.opener = new_opener()
        self.username = ""
        self.password = ""
        self.captcha_required = False
        self.captcha_bytes = b""


SESSIONS = {}


class ICSHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SCAU-ICS/1.0"
    debug = False

    def log_message(self, fmt, *args):
        print(f"[web] {self.address_string()} - {fmt % args}")

    def _send_text(self, text, status=200):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_ics(self, ics, filename):
        data = ics.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        quoted = urllib.parse.quote(filename)
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/captcha":
            qs = urllib.parse.parse_qs(parsed.query)
            sid = qs.get("session", [""])[0]
            state = SESSIONS.get(sid)
            if not state or not state.captcha_bytes:
                self.send_error(404, "验证码已过期，请返回重试")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(state.captcha_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(state.captcha_bytes)
            return
        self._send_text(_page_html())

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/fetch":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        username = (fields.get("username") or [""])[0].strip()
        password = (fields.get("password") or [""])[0]
        source = (fields.get("source") or ["jwzf"])[0].strip().lower() or "jwzf"
        start_date = (fields.get("start_date") or [""])[0].strip() or None
        captcha = (fields.get("captcha") or [""])[0].strip() or None
        sid = (fields.get("session") or [""])[0] or uuid.uuid4().hex

        if sid not in SESSIONS:
            SESSIONS[sid] = SessionState()
        state = SESSIONS[sid]
        state.username = username
        state.password = password
        state.source = source

        if not username or not password:
            self._send_text(_page_html(
                sid, "请输入学号和密码", "err",
                username=username, password=password, source=source, start_date=start_date or "",
            ))
            return

        try:
            if source == "jwzf":
                if not start_date:
                    xnm, xqm = _old_xnxq(None)
                    start_date = _default_old_start(xnm, xqm).isoformat()
                login_jwzf(state.opener, username, password)
                ics, xnxq, count = fetch_and_build_old(
                    state.opener, username, start_date=start_date, debug=self.debug,
                )
                filename = safe_filename(f"{username}_{xnxq}课表.ics")
                del SESSIONS[sid]
                print(f"生成成功：{filename}（{count} 条课程安排）")
                self._send_ics(ics, filename)
                return

            if not state.captcha_required:
                try:
                    state.captcha_required = captcha_required(state.opener)
                except Exception:
                    state.captcha_required = False
            if state.captcha_required and not captcha:
                try:
                    state.captcha_bytes = captcha_image(state.opener)
                except Exception:
                    state.captcha_bytes = b""
                self._send_text(_page_html(
                    sid, "请输入图片中的验证码", "ok", need_captcha=True,
                    username=state.username, password=state.password,
                    source=source, start_date=start_date or "",
                ))
                return

            token = login(state.opener, username, password, captcha)
            ics, xnxq, count = fetch_and_build(state.opener, token, debug=self.debug)
            filename = safe_filename(f"{username}_{xnxq}课表.ics")
            del SESSIONS[sid]
            print(f"生成成功：{filename}（{count} 条课程安排）")
            self._send_ics(ics, filename)
        except ScraperError as exc:
            # 验证码错误时刷新验证码，避免用户反复输入旧图
            if state.captcha_required:
                try:
                    state.captcha_bytes = captcha_image(state.opener)
                except Exception:
                    state.captcha_bytes = b""
                self._send_text(_page_html(
                    sid, str(exc), "err", need_captcha=True,
                    username=state.username, password=state.password,
                    source=source, start_date=start_date or "",
                ))
            else:
                self._send_text(_page_html(
                    sid, str(exc), "err",
                    username=state.username, password=state.password,
                    source=source, start_date=start_date or "",
                ))
        except Exception as exc:  # 防止服务崩溃
            self._send_text(_page_html(
                sid, f"发生未知错误：{exc}", "err",
                username=state.username, password=state.password,
                source=source, start_date=start_date or "",
            ))


def serve_command(args):
    host, port = args.host, args.port
    server = http.server.ThreadingHTTPServer((host, port), ICSHandler)
    ICSHandler.debug = args.debug
    if args.debug:
        print("调试模式已开启，接口原始返回会保存到当前目录")
    url = f"http://{host}:{port}/"
    print(f"网页版已启动：{url}")
    print("本工具由 zeta 制作")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="华南农业大学课表转 ICS 工具")
    sub = parser.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch", help="登录教务系统并下载课表 ICS")
    p_fetch.add_argument("--source", default="jwzf", choices=("jwzf", "jwxt"),
                         help="教务系统：jwzf（正方版，默认）或 jwxt（新版）")
    p_fetch.add_argument("--username", help="学号")
    p_fetch.add_argument("--password", help="密码（不推荐在命令行明文输入）")
    p_fetch.add_argument("--semester", help="学期，例如 2025-2026-1")
    p_fetch.add_argument("--start-date", help="本学期第 1 周周一的日期，例如 2026-09-01")
    p_fetch.add_argument("--out-dir", default=".", help="输出目录")
    p_fetch.add_argument("--captcha", help="验证码")
    p_fetch.add_argument("--debug", action="store_true", help="保存接口原始 JSON")
    p_fetch.set_defaults(func=fetch_command)

    p_convert = sub.add_parser("convert", help="用浏览器里复制的 JSON 转换 ICS（备用模式）")
    p_convert.add_argument("--calendar-json", help="findWeekCalendarList 的原始 JSON 文件（jwxt 新版需要）")
    p_convert.add_argument("--timetable-json", required=True,
                           help="xskbcx_cxXsgrkb（jwzf）或 searchOneXskbList（jwxt）的原始 JSON 文件")
    p_convert.add_argument("--semester", help="学期，例如 2025-2026-1")
    p_convert.add_argument("--start-date", help="本学期第 1 周周一的日期，例如 2026-09-01")
    p_convert.add_argument("--name", help="日历名称")
    p_convert.add_argument("--out-dir", default=".", help="输出目录")
    p_convert.set_defaults(func=lambda args: write_output(
        *convert_command(args), args.out_dir
    ))

    p_serve = sub.add_parser("serve", help="启动网页版")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8123)
    p_serve.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p_serve.add_argument("--debug", action="store_true", help="保存接口原始返回，便于排查")
    p_serve.set_defaults(func=serve_command)

    args = parser.parse_args()
    if not args.command:
        # 双击打包后的 exe 时默认启动网页版
        args.func = serve_command
        args.host = "127.0.0.1"
        args.port = 8123
        args.no_open = False
        args.debug = False
    try:
        args.func(args)
    except ScraperError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
