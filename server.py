#!/usr/bin/env python3
"""Moodle MIREA MCP — доступ к online-edu.mirea.ru через сессионную cookie.

Токены Web Services на сервере МИРЭА закрыты админом (вход только через SSO),
а большинство внешних функций запрещено через AJAX. Поэтому гибридная схема:
- AJAX (lib/ajax/service.php) — календарь, свои курсы, любые ajax-разрешённые функции;
- серверные HTML-страницы — содержимое курсов, задания, оценки, форумы.
Cookie MoodleSession живёт в файле MOODLE_COOKIE_FILE; keep-alive LaunchAgent
(ru.mirea.moodle-keepalive) продлевает сессию каждые 20 минут.
"""
import html as htmllib
import json
import os
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("MOODLE_BASE", "https://online-edu.mirea.ru")
COOKIE_FILE = os.environ.get("MOODLE_COOKIE_FILE", os.path.expanduser("~/.zcode/moodle_cookie"))
MAX_RESULT = 12000  # обрезка больших ответов, чтобы не раздувать контекст

mcp = FastMCP("moodle-mirea", instructions="""
Доступ к Moodle-порталу МИРЭА (online-edu.mirea.ru) без токенов Web Services: через
сессионную cookie MoodleSession (файл из env MOODLE_COOKIE_FILE, по умолчанию
~/.zcode/moodle_cookie). Ошибка MoodleSessionDead или «страница отдала логин» = сессия
истекла: попроси пользователя обновить значение cookie из браузера (DevTools → Cookies).
Схема: разрешённые AJAX-функции Moodle (raw_ajax) + парсинг серверного HTML (остальное).

Типовой цикл по заданию: course_assignments(courseid) → cmid нужного задания → материал
и контекст задания — в разделе «Ссылки:» ответа raw_page("/mod/assign/view.php?id=CMID")
→ download_file (скачать материал) → выполнение → upload_assignment_file(cmid, file_path),
который отправляет ответ преподавателю СРАЗУ, без черновиков (если у задания включён режим
черновика, отправка «Отправить на оценивание» выполняется автоматически).

Источники cmid задания: course_assignments (поле cmid у каждого задания), course_deadlines
(url событий), раздел «Ссылки:» в raw_page/course_content. core_course_get_contents на
портале отключён (servicenotavailable) — используй course_content/raw_page. Ошибка
servicenotavailable означает «функция не в белом списке AJAX», а НЕ мёртвую сессию.

Ответы инструментов обрезаются до 12000 символов (параметры с ссылками — до 16000).
""")

_state = {"sesskey": None, "userid": None}


class MoodleSessionDead(RuntimeError):
    """Серверная сессия истекла — нужно обновить cookie-файл."""


def _cookie() -> str:
    raw = Path(COOKIE_FILE).read_text().strip()
    if not raw:
        raise MoodleSessionDead(f"Файл {COOKIE_FILE} пуст — запиши туда значение MoodleSession")
    return raw if raw.startswith("MoodleSession=") else "MoodleSession=" + raw


def _request(path: str, data: bytes | None = None, content_type: str | None = None) -> str:
    headers = {"Cookie": _cookie(), "User-Agent": "Mozilla/5.0"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} на {path}: {e.read()[:200]}")


def _page(path: str) -> str:
    """GET html-страницы; распознаёт редирект на логин."""
    html = _request(path)
    if "login/index.php" in html and "sesskey" not in html:
        raise MoodleSessionDead(f"Сессия истекла (страница {path} отдала логин): обнови ~/.zcode/moodle_cookie")
    return html


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("tr", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "br", "section", "article"):
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html2text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    txt = htmllib.unescape("".join(p.out))
    txt = re.sub(r"[ \t]+", " ", txt)
    txt = re.sub(r"\n\s*\n+", "\n", txt)
    return txt.strip()


def _celltext(html: str) -> str:
    txt = htmllib.unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", txt).strip()


def _extract_links(html: str, limit: int = 80) -> list[str]:
    """Ссылки на .php-страницы (view.php → cmid, pluginfile.php → файлы) с анкорами."""
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, text = htmllib.unescape(m.group(1)), _celltext(m.group(2))
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        if not any(k in href for k in ("/mod/", "pluginfile.php", "draftfile.php",
                                       "/repository/", "/course/view.php")):
            continue
        key = href.split("#")[0] + "|" + text
        if key in seen:
            continue
        seen.add(key)
        out.append(f"- {text} — {href}" if text else f"- {href}")
        if len(out) >= limit:
            break
    return out


def _after(txt: str, anchors: list[str]) -> str:
    """Отрезает навигационный мусор: возвращает текст после первого найденного якоря."""
    for a in anchors:
        i = txt.find(a)
        if i >= 0:
            return txt[i + len(a):].strip()
    return txt


def _sesskey(force: bool = False) -> str:
    if _state["sesskey"] and not force:
        return _state["sesskey"]
    m = re.search(r'"sesskey":"([A-Za-z0-9]+)"', _page("/my/")) or re.search(
        r'name="sesskey" value="([A-Za-z0-9]+)"', _page("/my/")
    )
    if not m:
        raise RuntimeError("sesskey не найден на /my/ — структура страницы изменилась?")
    _state["sesskey"] = m.group(1)
    return _state["sesskey"]


def _userid() -> int:
    if _state["userid"]:
        return _state["userid"]
    m = re.search(r'data-userid="(\d+)"', _page("/my/")) or re.search(r'"userid":(\d+)', _page("/my/"))
    if not m:
        raise RuntimeError("Не удалось определить свой userid из /my/")
    _state["userid"] = int(m.group(1))
    return _state["userid"]


def ajax(method: str, args: dict, _retried: bool = False):
    """Вызов внешней функции Moodle через session-AJAX с авторетаем при ротации sesskey."""
    sk = _sesskey(force=_retried)
    body = json.dumps([{"index": 0, "methodname": method, "args": args}]).encode()
    try:
        resp = json.loads(_request(f"/lib/ajax/service.php?sesskey={sk}", data=body, content_type="application/json"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Не-JSON ответ на {method}: {e}")
    item = resp[0] if isinstance(resp, list) and resp else {}
    if item.get("error"):
        exc = item.get("exception") or {}
        code = str(exc.get("errorcode", ""))
        msg = (str(exc.get("message", "")) + " " + str(exc.get("debuginfo", ""))).strip()
        if not _retried and "sesskey" in msg.lower():
            return ajax(method, args, _retried=True)
        if code in ("requirelogin", "sessionexpired", "loggedoutas"):
            raise MoodleSessionDead(f"Сессия истекла ({code}): обнови ~/.zcode/moodle_cookie")
        raise RuntimeError(f"Moodle {code or 'error'}: {msg[:400]}")
    return item.get("data")


def _cut(obj, limit: int = MAX_RESULT) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)
    return s if len(s) <= limit else s[:limit] + f"\n…обрезано ({len(s)} символов всего)"


def _trim_events(events: list) -> list:
    out = []
    for e in events or []:
        out.append({
            "name": e.get("name"),
            "course": (e.get("course") or {}).get("fullname"),
            "начало": time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("timestart", 0))),
            "длительность_ч": round(e.get("timeduration", 0) / 3600, 1),
            "тип_действия": (e.get("action") or {}).get("name"),
            "url": e.get("url") or (e.get("action") or {}).get("url"),
        })
    return out


@mcp.tool()
def profile_info() -> str:
    """Кто я в системе: ФИО, email, группы и прочие поля профиля (парсинг страницы профиля)."""
    return _cut(html2text(_page("/user/profile.php"))[:3000])


@mcp.tool()
def my_courses() -> str:
    """Мои курсы: id, названия, прогресс, даты начала/конца. Источник — дашборд (AJAX)."""
    data = ajax("core_course_get_enrolled_courses_by_timeline_classification",
                {"classification": "all", "limit": 0, "offset": 0})
    slim = [{
        "id": c.get("id"),
        "название": c.get("fullname"),
        "shortname": c.get("shortname"),
        "прогресс_%": c.get("progress"),
        "начало": time.strftime("%Y-%m-%d", time.localtime(c["startdate"])) if c.get("startdate") else None,
        "конец": time.strftime("%Y-%m-%d", time.localtime(c["enddate"])) if c.get("enddate") else None,
    } for c in (data or {}).get("courses", [])]
    return _cut(slim)


@mcp.tool()
def upcoming_deadlines(days: int = 14) -> str:
    """Ближайшие события календаря (дедлайны заданий и пр.) на N дней вперёд.

    Args:
        days: горизонт поиска в днях (по умолчанию 14, максимум 90).
    """
    now = int(time.time())
    days = min(max(int(days), 1), 90)
    data = ajax("core_calendar_get_action_events_by_timesort",
                {"timesortfrom": now - 86400, "timesortto": now + days * 86400, "limitnum": 50})
    return _cut(_trim_events((data or {}).get("events", [])))


@mcp.tool()
def course_deadlines(courseid: int) -> str:
    """Все события календаря конкретного курса (включая прошедшие).

    В url каждого события есть cmid связанного задания/ресурса — второй
    источник cmid после course_assignments.

    Args:
        courseid: id курса (из my_courses).
    """
    data = ajax("core_calendar_get_action_events_by_course",
                {"courseid": int(courseid), "limitnum": 50})
    return _cut(_trim_events((data or {}).get("events", [])))


@mcp.tool()
def course_content(courseid: int) -> str:
    """Содержимое курса: секции, ресурсы + раздел «Ссылки:» (cmid и pluginfile каждого элемента).

    Args:
        courseid: id курса (из my_courses).
    """
    html = _page(f"/course/view.php?id={int(courseid)}")
    txt = _after(html2text(html), ["Открыть оглавление курса", "Начало курса", "Тема "])
    links = _extract_links(html)
    if links:
        txt += "\n\nСсылки:\n" + "\n".join(links)
    return _cut(txt, 16000)


@mcp.tool()
def course_assignments(courseid: int) -> str:
    """Задания курса со сроками и статусами сдачи + cmid каждого (парсинг /mod/assign/index.php).

    cmid нужен для открытия задания (/mod/assign/view.php?id=...) и для
    upload_assignment_file. «ячейки» — колонки таблицы после названия
    (срок, статус ответа, оценка).

    Args:
        courseid: id курса (из my_courses).
    """
    html = _page(f"/mod/assign/index.php?id={int(courseid)}")
    out, section = [], ""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        am = re.search(r'<a[^>]*href="[^"]*mod/assign/view\.php\?id=(\d+)[^"]*"[^>]*>(.*?)</a>', tr, re.S)
        if am:
            name = _celltext(am.group(2))
            cells = [_celltext(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            cells = [c for c in cells if c and c != name]
            if len(cells) == 4:  # колонки: Секция | Задание | Срок | Ответ | Оценка
                section = cells[0]
                cells = cells[1:]
            out.append({"cmid": int(am.group(1)), "секция": section, "название": name, "ячейки": cells})
        else:
            head = re.search(r"<t[hd][^>]*colspan[^>]*>(.*?)</t[hd]>", tr, re.S)
            if head and _celltext(head.group(1)):
                section = _celltext(head.group(1))
    return _cut(out)


@mcp.tool()
def course_grades(courseid: int) -> str:
    """Оценки по курсу: таблица элементов оценивания (парсинг отчёта оценок).

    Args:
        courseid: id курса (из my_courses).
    """
    txt = html2text(_page(f"/grade/report/user/index.php?id={int(courseid)}"))
    i = txt.find("Оценка")
    return _cut(txt[i:] if i >= 0 else txt)


@mcp.tool()
def raw_ajax(methodname: str, args: dict) -> str:
    """Универсальный вызов внешней функции Moodle через AJAX API (только ajax-разрешённые).

    Рабочие примеры: core_calendar_get_action_events_by_timesort,
    core_course_get_enrolled_courses_by_timeline_classification (args строго
    {"classification":"all","limit":0,"offset":0}), core_message_get_conversations.
    ОТКЛЮЧЕНЫ на портале (servicenotavailable): core_course_get_contents,
    mod_assign_get_assignments, core_enrol_get_users_courses,
    gradereport_user_get_grade_items — для них есть HTML-инструменты этого сервера.
    Ошибка servicenotavailable = функция не в белом списке, а не мёртвая сессия.

    Args:
        methodname: имя внешней функции Moodle.
        args: словарь аргументов функции.
    """
    return _cut(ajax(methodname, args))


@mcp.tool()
def raw_page(path: str, with_links: bool = True) -> str:
    """Текст любой страницы портала (серверный рендер), опционально с ссылками.

    Args:
        path: путь после домена, например /mod/assign/view.php?id=983260.
        with_links: добавить раздел «Ссылки:» (текст — href) для .php-адресов —
            оттуда берутся cmid заданий и прямые ссылки на файлы (pluginfile.php).
    """
    if not path.startswith("/") or ".." in path:
        raise RuntimeError("Нужен абсолютный путь, начинающийся с /")
    html = _page(path)
    txt = html2text(html)
    if with_links:
        links = _extract_links(html)
        if links:
            txt += "\n\nСсылки:\n" + "\n".join(links)
    return _cut(txt, 16000)


@mcp.tool()
def download_file(url: str, save_to: str = "") -> str:
    """Скачать файл с портала (pluginfile.php и любой другой путь) на диск.

    Args:
        url: полный URL или путь на online-edu.mirea.ru, например /pluginfile.php/...
        save_to: куда сохранить; по умолчанию ~/Downloads/<имя файла из URL>.
    """
    from urllib.parse import urlparse
    full = url if url.startswith("http") else BASE + url
    if urlparse(full).netloc != urlparse(BASE).netloc:
        raise RuntimeError("Разрешены только ссылки на домен портала")
    req = urllib.request.Request(full, headers={"Cookie": _cookie(), "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blob = r.read()
        ctype = r.headers.get("Content-Type", "")
    if "text/html" in ctype and b"login/index.php" in blob[:4000]:
        raise MoodleSessionDead("Вместо файла отдалась страница входа: сессия истекла, обнови ~/.zcode/moodle_cookie")
    name = os.path.basename(urlparse(full).path) or "file"
    target = os.path.expanduser(save_to) if save_to else os.path.join(os.path.expanduser("~/Downloads"), name)
    with open(target, "wb") as f:
        f.write(blob)
    return f"Сохранено: {target} ({len(blob)} байт, {ctype or 'тип не указан'})"


def _multipart(fields: dict, file_field: str, filename: str, content: bytes, ctype: str) -> tuple[bytes, str]:
    boundary = "----ZCodeMoodleBoundary9f3a1c"
    body = b""
    for k, v in fields.items():
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        ).encode()
    body += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


@mcp.tool()
def upload_assignment_file(cmid: int, file_path: str) -> str:
    """Загрузить файл как ответ на задание Moodle (mod/assign) и сохранить.

    Политика пользователя (2026-10-05): черновики не нужны — ответ должен сразу
    уходить преподавателю. Если у задания включён режим черновика, после
    сохранения инструмент сам выполняет «Отправить на оценивание» (принимая
    заявление о самостоятельности работы, если оно требуется). У заданий без
    режима черновика сохранение уже отправляет ответ автоматически.

    Args:
        cmid: id модуля задания (mod/assign/view.php?id=...).
        file_path: локальный путь к файлу ответа (например, PDF отчёта).
    """
    p = Path(file_path)
    if not p.is_file():
        raise RuntimeError(f"Файл не найден: {file_path}")
    edit = _page(f"/mod/assign/view.php?id={int(cmid)}&action=editsubmission")
    sk_m = re.search(r'"sesskey":"([A-Za-z0-9]+)"', edit)
    if not sk_m:
        raise MoodleSessionDead("sesskey не найден: сессия истекла или это не страница сдачи")
    sk = sk_m.group(1)
    hidden = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', edit):
        tag = m.group(0)
        nm = re.search(r'name="([^"]+)"', tag)
        vl = re.search(r'value="([^"]*)"', tag)
        if nm:
            hidden[nm.group(1)] = vl.group(1) if vl else ""
    fm = re.search(r'<input[^>]*files_filemanager[^>]*>', edit)
    if not fm:
        raise RuntimeError("Файл-менеджер не найден на форме — задание принимает не файлы?")
    itemid = re.search(r'value="(\d+)"', fm.group(0)).group(1)
    ru = re.search(r'"repositories":\{', edit)
    repo_id = None
    if ru:
        for m in re.finditer(r'"id":"(\d+)","name":"[^"]*","type":"upload"', edit):
            repo_id = m.group(1)
    if not repo_id:
        raise RuntimeError("Репозиторий «Загрузить файл» не найден в форме")

    content = p.read_bytes()
    fields = {"sesskey": sk, "repo_id": repo_id, "itemid": itemid, "env": "filemanager",
              "ppage": "", "title": p.name, "author": "", "upload_button": "Загрузить этот файл"}
    body, boundary = _multipart(fields, "repo_upload_file", p.name, content,
                                "application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream")
    html = _request("/repository/repository_ajax.php?action=upload", data=body,
                    content_type=f"multipart/form-data; boundary={boundary}")
    if '"error"' in html[:200] and "error" in json.loads(html).get("error", "").lower():
        raise RuntimeError(f"Ошибка загрузки в черновик-область: {html[:200]}")

    post = dict(hidden)
    post.update({"sesskey": sk, "files_filemanager": str(itemid), "submitbutton": "Сохранить"})
    _request(f"/mod/assign/view.php?id={int(cmid)}&action=savesubmission", data=urllib.parse.urlencode(post).encode(),
             content_type="application/x-www-form-urlencoded")

    view = _page(f"/mod/assign/view.php?id={int(cmid)}")
    st = re.search(r"(Отправлено для оценивания|Черновик|Нет ответа на задание|Ответ не представлен)", view)
    status = st.group(0) if st else "не определён"
    if status == "Черновик":
        sub = _page(f"/mod/assign/view.php?id={int(cmid)}&action=submit")
        data = {}
        for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', sub):
            tag = m.group(0)
            nm = re.search(r'name="([^"]+)"', tag)
            vl = re.search(r'value="([^"]*)"', tag)
            if nm:
                data[nm.group(1)] = vl.group(1) if vl else ""
        data.update({"id": str(int(cmid)), "action": "submit", "sesskey": sk,
                     "submitbutton": "Отправить на оценивание"})
        if "submissionstatement" in sub:
            data["submissionstatement"] = "1"
        _request(f"/mod/assign/view.php?id={int(cmid)}", data=urllib.parse.urlencode(data).encode(),
                 content_type="application/x-www-form-urlencoded")
        view = _page(f"/mod/assign/view.php?id={int(cmid)}")
        st = re.search(r"(Отправлено для оценивания|Черновик|Нет ответа на задание|Ответ не представлен)", view)
        status = st.group(0) if st else "не определён"
    ok = p.name in view
    return (f"Готово. Статус задания: {status}; "
            f"файл «{p.name}» {'в ответе' if ok else 'НЕ найден в ответе — проверь вручную!'}")


if __name__ == "__main__":
    mcp.run()
