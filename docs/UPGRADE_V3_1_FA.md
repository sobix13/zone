# نصب آپدیت ۳٫۱ با Termius

بسته در محیط آزمایشی آماده شده است؛ اجرای واقعی روی VPS با شما است. قابلیت جدید پس از نصب، تا انتخاب رول‌ها فعال نمی‌شود.

## ورود و تأیید مسیر

در Termius به VPS وصل شوید. دستور شِل روت `sudo -i` است؛ نه `sudu`. فقط با حساب دارای مجوز sudo اجرا کنید. در صورت رد دسترسی، با حساب مجاز وارد شوید.

```bash
sudo -i
systemctl show melee-zone.service --property=WorkingDirectory --property=User --property=ExecStart --no-pager
```

مثال‌ها برای مسیر `/root/Melee-Zone` و سرویس `melee-zone.service` هستند. مقادیر زیر را مطابق خروجی واقعی تنظیم کنید؛ اگر بررسی مسیر خطا داد ادامه ندهید.

```bash
MZ_APP=/root/Melee-Zone
MZ_UNIT=melee-zone.service
test -d "$MZ_APP" && test -f "$MZ_APP/.env"
```

## بکاپ قبل از آپدیت

نصب‌کننده قبل از جایگزینی کد، بکاپ کد و SQLite سازگار با WAL می‌گیرد، آن را کنترل می‌کند و مهاجرت را روی کپی آزمایش می‌کند. `.env` فعلی جایگزین نمی‌شود. برای بکاپ دستی مستقل، مفسر محیط مجازی موجود را از `ExecStart` پیدا کنید؛ مسیر نمونه زیر را در صورت نیاز تغییر دهید. بعد از تأیید مفسر و مسیر، بلوک بکاپ را اجرا کنید.

```bash
MZ_PY="$MZ_APP/venv/bin/python"
test -x "$MZ_PY"
```

```bash
umask 077
MZ_BACKUP=$(mktemp -d /root/melee-before-v31-XXXXXX)
tar -czf "$MZ_BACKUP/application.tar.gz" --exclude=venv --exclude=.venv --exclude=.releases --exclude=backups --exclude=runtime -C "$MZ_APP" .
"$MZ_PY" -c 'import pathlib,sqlite3,sys; from dotenv import dotenv_values; app=pathlib.Path(sys.argv[1]); cfg=dotenv_values(app/".env"); db=pathlib.Path(cfg.get("DATABASE_PATH") or "bot.db"); db=db if db.is_absolute() else app/db; src=sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True); dst=sqlite3.connect(pathlib.Path(sys.argv[2])/"database.sqlite"); src.backup(dst); assert dst.execute("PRAGMA quick_check").fetchone()[0]=="ok"; dst.close(); src.close(); print("SQLite backup verified")' "$MZ_APP" "$MZ_BACKUP"
chmod 600 "$MZ_BACKUP/application.tar.gz" "$MZ_BACKUP/database.sqlite"
printf 'Private backup: %s\n' "$MZ_BACKUP"
```

اگر هر مرحله خطا داد، ادامه ندهید. tar ممکن است `.env` و DB خام هم داشته باشد؛ خصوصی نگه دارید و در GitHub نفرستید. نسخه `database.sqlite` بکاپ سازگار است؛ DB خام داخل tar هنگام اجرای بات لزوماً سازگار نیست. توکن یا محتوای `.env` را در چت نفرستید.

## انتقال و نصب

فایل تحویلی `Melee-Zone-V3.1-update.tar.gz` را با روش انتقال فایل در دسترس خود به `/tmp` سرور برسانید. دستورهای زیر دانلود انجام نمی‌دهند. پس از موفقیت هر مرحله، مرحله بعد را اجرا کنید.

```bash
test -f /tmp/Melee-Zone-V3.1-update.tar.gz
MZ_STAGE=$(mktemp -d /tmp/melee-v31-XXXXXX)
tar -xzf /tmp/Melee-Zone-V3.1-update.tar.gz -C "$MZ_STAGE"
bash "$MZ_STAGE/melee-zone-v3.1/install.sh" --app-dir "$MZ_APP" --service "$MZ_UNIT" --dry-run
```

Dry run فقط مسیر و هش فایل‌ها را کنترل می‌کند؛ تست مهاجرت یا تماس با دیسکورد نیست. بعد از موفقیت، نصب واقعی:

```bash
bash "$MZ_STAGE/melee-zone-v3.1/install.sh" --app-dir "$MZ_APP" --service "$MZ_UNIT"
```

سرویس قبلی را قبل از این مرحله دستی خاموش نکنید؛ نصب‌کننده ابتدا چک‌های لازم را انجام می‌دهد. مسیر بکاپ خروجی نصب را نگه دارید. تکرار کورکورانه نصب پس از خطا لازم نیست.

## کنترل و فعال‌سازی

برای نام‌ها و پورت‌های پیش‌فرض:

```bash
systemctl status melee-zone.service melee-zone-recovery.service --no-pager
journalctl -u melee-zone.service -n 60 --no-pager
curl --fail --silent http://127.0.0.1:3020/ready
```

در دیسکورد `/health` و `/doctor` را اجرا کنید و موجودی MC/پست‌های قدیمی را مقایسه کنید. `setup_reset` یا حذف DB لازم نیست. در `/admin_panel`، **Review support → Setup roles** را باز و رول‌ها را ذخیره کنید. مادها خودشان ظرفیت اعلام می‌کنند:

```text
/support panel
/support availability reviewers:10 members:0
/support status
/review_analytics days:14
/review_analytics_status job_id:REPORT_ID
/team_messages
```

`REPORT_ID` شناسه واقعی خروجی بات است. برای بررسی محتوای اعضا، رول سوم و ظرفیت `members` را هم انتخاب کنید. راهنمای کامل در `docs/REVIEW_SUPPORT.md` است.

## خطا و برگشت

مهاجرت افزایشی است. نصب‌کننده در شکست مرحله شروع، کد/یونیت قبلی را برمی‌گرداند و MC جدید ثبت‌شده بعد از شروع را حفظ می‌کند. DB قدیمی را کورکورانه روی DB جدید کپی نکنید؛ فعالیت و MC تازه از بین می‌رود. برای برگشت دستی کد از دستورهای `docs/OPERATIONS.md` با مسیر بکاپ واقعی استفاده کنید. مشکل توکن، intent، مجوز کانال یا کل میزبان باید در همان محیط اصلاح شود.
