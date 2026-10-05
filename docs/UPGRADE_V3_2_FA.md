# آپدیت کامل با Termius

این راهنما مخصوص صاحب سرور است، نه دفترچهٔ مادریتورها. بستهٔ جدید همهٔ قابلیت‌های ۳٫۱ و کنترل دسترسی جدید را دارد. انتشار کد در گیت‌هاب به‌تنهایی بات روی VPS را آپدیت نمی‌کند.

## ورود و مسیر واقعی

با حساب دارای مجوز sudo وارد Termius شوید. دستور درست `sudo -i` است. اگر مجوز ندارید، از حساب مجاز استفاده کنید؛ محدودیت دسترسی را دور نزنید.

```bash
sudo -i
systemctl show melee-zone.service --property=WorkingDirectory --property=ExecStart --property=User --no-pager
```

مسیر و نام سرویس زیر نمونه است. آن‌ها را با خروجی واقعی تطبیق دهید. مفسر `MZ_PY` باید همان مفسر محیط فعلی باشد که در ExecStart دیده‌اید. در صورت خطا ادامه ندهید.

```bash
MZ_APP=/root/Melee-Zone
MZ_UNIT=melee-zone.service
MZ_PY="$MZ_APP/venv/bin/python"
test -d "$MZ_APP" && test -f "$MZ_APP/.env" && test -x "$MZ_PY"
```

## ابتدا بکاپ خصوصی

این بکاپ دستی مستقل را پیش از نصب بگیرید. بکاپ SQLite با روش سازگار با WAL گرفته می‌شود؛ دیتابیس خام داخل tar هنگام روشن بودن بات مرجع بازیابی نیست. فایل tar ممکن است توکن داشته باشد؛ آن را خصوصی نگه دارید و در گیت‌هاب یا چت نفرستید.

```bash
umask 077
MZ_BACKUP=$(mktemp -d /root/melee-before-v32-XXXXXX)
tar -czf "$MZ_BACKUP/application.tar.gz" --exclude=venv --exclude=.venv --exclude=.releases --exclude=backups --exclude=runtime --exclude=.git -C "$MZ_APP" .
"$MZ_PY" -c 'import pathlib,sqlite3,sys; from dotenv import dotenv_values; app=pathlib.Path(sys.argv[1]); cfg=dotenv_values(app/".env"); db=pathlib.Path(cfg.get("DATABASE_PATH") or "bot.db"); db=db if db.is_absolute() else app/db; src=sqlite3.connect("file:"+str(db)+"?mode=ro",uri=True); dst=sqlite3.connect(pathlib.Path(sys.argv[2])/"database.sqlite"); src.backup(dst); assert dst.execute("PRAGMA quick_check").fetchone()[0]=="ok"; dst.close(); src.close(); print("SQLite backup verified")' "$MZ_APP" "$MZ_BACKUP"
chmod 600 "$MZ_BACKUP/application.tar.gz" "$MZ_BACKUP/database.sqlite"
printf 'Private backup: %s\n' "$MZ_BACKUP"
```

## دریافت و نصب از پوشهٔ جدا

فایل `Melee-Zone-V3.2-update.tar.gz` را با انتقال فایل به `/tmp` VPS برسانید. یا نسخهٔ منتشرشده را از مسیر بستهٔ ریپازیتوری دانلود کنید:

```bash
curl --fail --location --output /tmp/Melee-Zone-V3.2-update.tar.gz https://raw.githubusercontent.com/sobix13/zone/main/releases/v3.2/Melee-Zone-V3.2-update.tar.gz
curl --fail --location --output /tmp/Melee-Zone-V3.2-SHA256SUMS.txt https://raw.githubusercontent.com/sobix13/zone/main/releases/v3.2/SHA256SUMS.txt
cd /tmp
sha256sum --check --ignore-missing Melee-Zone-V3.2-SHA256SUMS.txt
```

بعد از موفقیت چک هش، در پوشهٔ موقت جدا استخراج کنید. `.env` یا دیتابیس را با فایل دیگری جایگزین نکنید. از `git pull` روی پوشهٔ زنده به‌عنوان جایگزین نصب کنترل‌شده استفاده نکنید.

```bash
MZ_STAGE=$(mktemp -d /tmp/melee-v32-XXXXXX)
tar -xzf /tmp/Melee-Zone-V3.2-update.tar.gz -C "$MZ_STAGE"
bash "$MZ_STAGE/melee-zone-v3.2/install.sh" --app-dir "$MZ_APP" --service "$MZ_UNIT" --dry-run
```

Dry run تنها مسیر و هش بسته را بررسی می‌کند. پس از موفقیت آن، نصب واقعی محیط مجازی جدا می‌سازد، بکاپ خود را می‌گیرد، مهاجرت را روی کپی آزمایش می‌کند، کد را نصب و شروع سرویس را کنترل می‌کند:

```bash
bash "$MZ_STAGE/melee-zone-v3.2/install.sh" --app-dir "$MZ_APP" --service "$MZ_UNIT"
```

اگر خطا رخ داد، خروجی خطا و مسیر بکاپ را نگه دارید؛ نصب را کورکورانه تکرار نکنید. نصب‌کننده در شکست مرحلهٔ شروع، کد و یونیت قبلی را برمی‌گرداند و MC تازهٔ ثبت‌شده پس از شروع را حفظ می‌کند. دیتابیس قدیمی را روی دیتابیس جدید کپی نکنید.

## کنترل بعد از نصب

برای نام و پورت پیش‌فرض:

```bash
systemctl status melee-zone.service melee-zone-recovery.service --no-pager
journalctl -u melee-zone.service -n 60 --no-pager
curl --fail --silent http://127.0.0.1:3020/ready
```

در دیسکورد `/health` و `/doctor` را اجرا و موجودی‌های قبلی را کنترل کنید. `setup_reset` لازم نیست. ادمین اصلی قبلی یا صاحب سرور وارد `/admin_access` شود و رول ماد، رول ادمین اصلی و افراد ادمین اصلی را انتخاب کند. مادها اساینمنت و MC را مستقیم انجام می‌دهند؛ تغییر تنظیمات حساس در Change requests منتظر تأیید می‌ماند.

چک‌های مجوز و گیت‌ویِ واقعی در `docs/LIVE_ACCEPTANCE.md` آمده است. اگر کل میزبان خاموش باشد، توکن لغو شده باشد یا Discord مجوز ندهد، راه بازیابی داخلی نمی‌تواند جای اصلاح آن محیط را بگیرد.
