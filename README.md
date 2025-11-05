# Discord Quran/Audio Bot – Production‑Ready (Python 3.11)

بوت ديسكورد صوتي لتشغيل القرآن والصوتيات من YouTube (أساسي) وFacebook (باستخدام كوكيز صالحة)، وروابط مباشرة/HLS/MP3، مع قائمة انتظار، بحث بالكلمات، مدير كوكيز مشفّر، لوج JSON مُهيكل، وإعدادات محفوظة في SQLite.

## المتطلبات
- Python 3.11+
- FFmpeg (مسار متاح في PATH)
- (اختياري) Docker و Docker Compose

### تثبيت FFmpeg
- **Linux (Debian/Ubuntu):**
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```
- **Windows:**
  1. نزّل FFmpeg (build) من: https://www.gyan.dev/ffmpeg/builds/
  2. فك الضغط وضع مجلد `bin/` في متغير PATH.
- **macOS (Homebrew):**
  ```bash
  brew install ffmpeg
  ```

## التشغيل محليًا
1. انسخ `.env.example` إلى `.env` واملأ `DISCORD_TOKEN` ويفضّل تعيين `COOKIES_ENCRYPTION_KEY` (مفتاح Fernet Base64). لإنشاء مفتاح:
   ```python
   from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())
   ```
2. أنشئ بيئة:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # على ويندوز: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. شغّل البوت:
   ```bash
   python bot.py
   ```

## التشغيل عبر Docker
```bash
docker compose up --build -d
```
- السجلات JSON محفوظة في `./logs/bot.jsonl` (على المضيف).

## الأوامر (Slash)
- `/join` — دخول القناة الصوتية الحالية.
- `/play <url|query>` — تشغيل رابط أو البحث بالكلمات (يعرض اختيارًا تفاعليًا عند البحث).
- `/search <query>` — بحث فقط.
- `/queue`، `/remove <index>`، `/move <from> <to>`، `/shuffle`، `/loop <off|one|all>`، `/now`، `/skip [count]`، `/pause`، `/resume`، `/stop`، `/volume <0-100>`، `/seek <mm:ss>`.
- `/settings` (عرض) و`/set <…>` لتعديل الإعدادات.
- `/dj set <@role>` — تعيين دور DJ.
- `/cookies set|info|test|delete` — إدارة الكوكيز (مشفرًا لكل سيرفر/مزود).
- `/admin ytdlp-update`، `/admin diag`، `/admin logs show [lines] [level]`، `/admin loglevel <…>`.

> **ملاحظة**: لا يتم عرض أي محتوى حسّاس في اللوج، ويتم تنفيذ Redaction تلقائي لأي حقل باسم يحوي `token/cookie/authorization`.

## الكوكيز (cookies.txt)
- بعض المصادر (خاصة Facebook/مقاطع Age‑Gate في YouTube) تتطلب cookies.txt صالحة.
- كيفية استخراج `cookies.txt` من المتصفح:
  - **Chrome/Edge**: إضافة **Get cookies.txt** من متجر الإضافات.
  - **Firefox**: إضافة **cookies.txt**.
  - احرص أن تكون لمجال المزوّد (youtube.com / facebook.com) وأن تكون حديثة.
- ارفع الملف باستخدام:
  ```
  /cookies set file:cookies.txt provider:youtube
  /cookies test provider:youtube
  ```

## خط الأنابيب الصوتي
`yt-dlp → FFmpeg (PCM 48kHz, stereo, loudnorm) → Discord (Opus)` مع إعادة محاولات تدريجية في حال انقطاع المصدر.

### FFmpeg args المستخدمة
```
-before_options: -ss <seekSec> -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin
-options:         -vn -ac 2 -f s16le -ar 48000 -filter:a loudnorm=i=-16:tp=-1.5
```

## سياسة الانفصال التلقائي
عند خلوّ الصف وتوقف التشغيل – يبدأ عداد الخمول (افتراضي 10 دقائق) ثم يترك القناة تلقائيًا. قابل للتعديل عبر `/set idle_minutes`.

## أمثلة سجلات (JSON مقتطف)
```json
{"ts":"2025-11-05T09:12:00Z","level":"INFO","event":"startup","trace_id":"e3a1b5a2c9d1","component":"admin","message":"Logged in as QuranBot#1234 (id=...)"}
{"ts":"2025-11-05T09:12:05Z","level":"INFO","event":"search_ok","trace_id":"6fdc1b2e77a1","component":"search","guild_id":123,"query":"سورة الكهف","results_count":5}
{"ts":"2025-11-05T09:12:10Z","level":"INFO","event":"extract_ok","trace_id":"b7d9a2e1c3f4","component":"extractor","guild_id":123,"url":"https://youtu.be/...","elapsed_ms":0}
{"ts":"2025-11-05T09:12:12Z","level":"INFO","event":"playback_start","trace_id":"a1b2c3d4e5f6","component":"voice","guild_id":123,"title":"سورة الكهف","url":"https://youtu.be/...","duration":1432}
{"ts":"2025-11-05T09:20:20Z","level":"INFO","event":"auto_leave","trace_id":"91ab2c3d4e5f","component":"voice","guild_id":123}
```

## اختبارات يدوية (Manual QA)
1. **تشغيل يوتيوب عادي**: `/play https://www.youtube.com/watch?v=BaW_jenozKc` → يعمل بدون كوكيز.
2. **Age‑Gate**: `/play <رابط يتطلب عمر>` → يفشل، ثم `/cookies set` و`/cookies test` → أعد `/play` فينجح.
3. **بحث سورة**: `/search "سورة الكهف"` ثم `/play "سورة الكهف"` → اختر نتيجة → تشغيل/إضافة للصف.
4. **إدارة الصف**: `/queue` → `/shuffle` → `/loop all` → `/skip`.
5. **فشل FFmpeg**: جرّب رابط غير صالح → تظهر رسالة مع تصنيف الخطأ.
6. **إدارة النظام**: `/admin diag`، `/admin logs show`، `/admin loglevel DEBUG`.

## ملاحظات أمان
- لا تحفظ أي كوكيز غير مشفرة. يخزنها البوت داخل SQLite مُشفّرة بـFernet (Per‑Guild/Provider).
- لا تُرسل الكوكيز للمستخدمين. يُعرض فقط `is_valid` و`last_validated_at`.
- يتم إنشاء ملف كوكيز مؤقت عند الحاجة وحذفه فورًا بعد الاستخدام.

## توسيع لاحق (/quran)
تم ترك Hook لإضافة مصدر MP3 ثابت لاحقًا (قوائم تشغيل جاهزة للقرآن) لتقليل الاعتماد على منصات عامة.
