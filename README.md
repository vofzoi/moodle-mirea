# moodle-mirea

**MCP-сервер для учебного портала МИРЭА [online-edu.mirea.ru](https://online-edu.mirea.ru)** — работает
без токенов Web Services (админ их закрыл) через сессионную cookie `MoodleSession`. Схема гибридная:
разрешённые AJAX-функции идут через `/lib/ajax/service.php`, всё остальное — парсинг серверного HTML.

Проверено с ZCode; подойдёт для любого MCP-клиента (Claude Desktop и т.п. — конфиг по аналогии).

> Зачем это всё: на МИРЭА вход только через SSO с 2FA/пасскеем, токены Web Services не выдаются,
> а большинство внешних функций Moodle запрещено на уровне AJAX. Этот сервер даёт агенту полный
> цикл: посмотреть задания → скачать материал → (выполнить) → загрузить ответ и отправить на оценивание.

## Возможности — 11 инструментов

| Инструмент | Что делает |
|---|---|
| `my_courses()` | Мои курсы: id, названия, прогресс, даты |
| `upcoming_deadlines(days=14)` | Ближайшие события календаря (дедлайны) на N дней |
| `course_deadlines(courseid)` | Все события курса, включая прошедшие (в `url` есть cmid) |
| `course_assignments(courseid)` | Задания курса: **cmid каждого**, секция, срок, статус сдачи |
| `course_content(courseid)` | Содержимое курса + раздел «Ссылки:» (mod-ссылки, pluginfile-адреса) |
| `course_grades(courseid)` | Таблица оценок курса |
| `profile_info()` | Свои ФИО, email, группы |
| `raw_ajax(methodname, args)` | Любая ajax-разрешённая WS-функция Moodle |
| `raw_page(path, with_links=True)` | Текст любой страницы портала + раздел «Ссылки:» |
| `download_file(url, save_to="")` | Скачать файл с портала (pluginfile.php и любой путь; годится и для HTML-страниц) |
| `upload_assignment_file(cmid, file_path)` | Прикрепить файл-ответ к заданию и **отправить на оценивание** |

Типовой цикл агента: `course_assignments` → взял cmid и материал из «Ссылки:» → `download_file` →
выполнил задание → `upload_assignment_file`. Политика сдачи — **без черновиков**: если у задания
включён режим черновика, инструмент сам выполняет «Отправить на оценивание» (и принимает заявление
о самостоятельности, если оно требуется). Ответ уходит преподавателю сразу.

## Установка

### 1. Код и зависимости

Нужны: Python 3.12+, git (curl уже есть на macOS и Linux, на Windows 10+ входит в состав).

**macOS / Linux:**
```bash
git clone https://github.com/vofzoi/moodle-mirea.git
cd moodle-mirea
python3.12 -m venv .venv
.venv/bin/pip install "mcp<2"
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/vofzoi/moodle-mirea.git
cd moodle-mirea
py -3.12 -m venv .venv
.venv\Scripts\pip install "mcp<2"
```

> Python 3.12 на Windows: `winget install Python.Python.3.12` или с python.org (отметь
> «Add python.exe to PATH»). Если `py -3.12` не находится — проверь `py --list`.
> Именно `mcp<2`: в mcp 2.x переименовали `FastMCP`, сервер собран под 1.x API.

### 2. Cookie сессии

1. В браузере зайди на `online-edu.mirea.ru` (SSO МИРЭА, 2FA/пасскей).
2. Открой DevTools (F12):
   - Chrome / Edge / Яндекс.Браузер: **Application → Cookies → online-edu.mirea.ru**
   - Firefox: **Хранилище → Куки → online-edu.mirea.ru**

   Скопируй значение cookie `MoodleSession` целиком (столбец «Значение»).
3. Сохрани в файл:

**macOS / Linux:**
```bash
mkdir -p ~/.zcode
echo 'MoodleSession=ЗНАЧЕНИЕ' > ~/.zcode/moodle_cookie
chmod 600 ~/.zcode/moodle_cookie
```

**Windows (PowerShell):**
```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.zcode" | Out-Null
Set-Content "$env:USERPROFILE\.zcode\moodle_cookie" "MoodleSession=ЗНАЧЕНИЕ"
```
(файл будет `C:\Users\<YOU>\.zcode\moodle_cookie`)

Проверка живости (200 = ок, 303/страница логина = протухла):

**macOS / Linux:**
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Cookie: $(cat ~/.zcode/moodle_cookie)" -A "Mozilla/5.0" \
  https://online-edu.mirea.ru/my/
```

**Windows (PowerShell):**
```powershell
curl.exe -s -o NUL -w "%{http_code}" -H "Cookie: $(Get-Content $env:USERPROFILE\.zcode\moodle_cookie)" -A "Mozilla/5.0" https://online-edu.mirea.ru/my/
```

> Cookie = твой identity в портале. Не шарить, не коммитить, chmod 600.

### 3. Подключение к MCP-клиенту

Для ZCode — в `~/.zcode/cli/config.json` (пути подставь свои):

```json
{
  "mcp": {
    "servers": {
      "moodle": {
        "type": "stdio",
        "command": "/Users/<YOU>/.zcode/mcp/moodle-mirea/.venv/bin/python",
        "args": ["/Users/<YOU>/.zcode/mcp/moodle-mirea/server.py"],
        "env": {
          "MOODLE_BASE": "https://online-edu.mirea.ru",
          "MOODLE_COOKIE_FILE": "/Users/<YOU>/.zcode/moodle_cookie"
        }
      }
    }
  }
}
```

**Windows** (в JSON двойные бэкслеши обязательны):
```json
{
  "mcp": {
    "servers": {
      "moodle": {
        "type": "stdio",
        "command": "C:\\Users\\<YOU>\\.zcode\\mcp\\moodle-mirea\\.venv\\Scripts\\python.exe",
        "args": ["C:\\Users\\<YOU>\\.zcode\\mcp\\moodle-mirea\\server.py"],
        "env": {
          "MOODLE_BASE": "https://online-edu.mirea.ru",
          "MOODLE_COOKIE_FILE": "C:\\Users\\<YOU>\\.zcode\\moodle_cookie"
        }
      }
    }
  }
}
```

Перезапусти клиент — инструменты появятся как `mcp__moodle__*`.

Сервер **самоописываемый**: при подключении MCP-клиент получает `instructions` (полный cheatsheet
по циклу работы, источникам cmid и кодам ошибок) и описание каждого инструмента из его docstring —
отдельные AGENTS.md/инструкции для агента не обязательны.

### 4. Keep-alive — автопродление сессии (опционально)

Сессия умирает примерно через час без активности. Скрипт пингует `/my/` каждые 20 минут и пишет
лог: `~/.zcode/moodle_keepalive.log` (macOS/Linux) или `C:\Users\<YOU>\.zcode\moodle_keepalive.log`
(Windows). Строки `OK` — сессия жива; `DEAD` — пора обновить cookie из браузера.

**macOS** — LaunchAgent одной командой:
```bash
./install_keepalive.sh
tail -f ~/.zcode/moodle_keepalive.log
```
Управление: `launchctl bootout gui/$(id -u)/ru.mirea.moodle-keepalive` (выключить),
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ru.mirea.moodle-keepalive.plist` (включить).

**Windows** — Планировщик заданий (PowerShell, под своим пользователем):
```powershell
schtasks /Create /F /TN "MoodleKeepAlive" /SC MINUTE /MO 20 `
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\<YOU>\.zcode\mcp\moodle-mirea\windows_keepalive.ps1"
schtasks /Run /TN "MoodleKeepAlive"
```
Вторая команда запускает проверку сразу (не ждать 20 минут). Управление:
`schtasks /Query /TN "MoodleKeepAlive"` — статус, `schtasks /Delete /TN "MoodleKeepAlive"` — удалить.
По умолчанию задание работает, пока ты залогинен в Windows; чтобы пинговать и без входа —
в свойствах задания включи «Выполнять вне зависимости от регистрации пользователя».

**Linux** — cron (`crontab -e`):
```cron
*/20 * * * * /путь/к/moodle-mirea/keepalive.sh
```

## Типовые ошибки

| Симптом | Причина и решение |
|---|---|
| `MoodleSessionDead` / «страница отдала логин» | Cookie протухла — обнови `~/.zcode/moodle_cookie` из браузера |
| `servicenotavailable` в `raw_ajax` | Функция не разрешена для AJAX на портале (например `core_course_get_contents`) — бери `raw_page`/`course_content` |
| «Репозиторий "Загрузить файл" не найден» | Задание принимает не файл (онлайн-текст и т.п.) |
| `download_file` вернул страницу входа | То же, что `MoodleSessionDead` — обнови cookie |
| curl с cookie даёт 303 | Сессия мёртвая для всех инструментов; не задваивай префикс `MoodleSession=` в заголовке |

## Как это работает внутри

- `sesskey` извлекается из `/my/` и кэшируется; AJAX-вызов: `POST /lib/ajax/service.php?sesskey=...`
  с телом `[{"index":0,"methodname":...,"args":{...}}]`; при ротации sesskey — авторетрай.
- HTML-страницы парсятся регексами (`mod/assign/index.php` — таблица
  «Секция \| Задание \| Срок \| Ответ \| Оценка», у МИРЭА секция печатается только в первой строке группы).
- Загрузка файла: `view.php?action=editsubmission` (sesskey, draft `itemid`, repo_id «Загрузить файл»)
  → `repository/repository_ajax.php?action=upload` (multipart) → `action=savesubmission` →
  при режиме черновиков ещё `action=submit` (+ `submissionstatement=1`).
- Ответы обрезаются до 12000 символов (`_cut`), чтобы не раздувать контекст агента.
- Весь сервер — один файл `server.py`, единственная зависимость — `mcp<2`.

## Ограничения и этика

- Инструмент для автоматизации **своих** учебных задач. Не ддосить портал: таймауты и обрезки
  настроены щадяще, keep-alive — один GET в 20 минут.
- Загруженные ответы уходят преподавателю от твоего имени — проверяй, что грузишь, до `upload_assignment_file`.
- Список ajax-разрешённых функций на портале может поменять админ — тогда `raw_ajax` для конкретной
  функции начнёт отдавать `servicenotavailable`, а парсинг HTML продолжит работать.
- Это не официальный продукт МИРЭА; portал может измениться — регексы придётся поправить.

## Лицензия

MIT — см. [LICENSE](LICENSE).
