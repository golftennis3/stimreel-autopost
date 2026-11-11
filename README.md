# Stimreel → Instagram (у хмарі)

GitHub сам генерує відео на stimreel.com (під акаунтом бота) і публікує Reel у @stim.reel.
Комп'ютер не потрібен.

## Запуск
Застосунок GitHub → репозиторій → **Actions → Post Reel → Run workflow**.
- `count` — скільки відео зробити й опублікувати;
- `publish` — зняти галочку, щоб лише згенерувати (відео — в розділі Artifacts запуску).

## Секрети (Settings → Secrets and variables → Actions)
- `STIMREEL_EMAIL`, `STIMREEL_PASSWORD` — акаунт бота на Stimreel;
- `IG_TOKEN`, `IG_USER_ID` — доступ до Instagram (заносить `cloud_keys.bat` з ноутбука).

## Що всередині
- `cloud_run.py` — статистика → генерація → публікація;
- `stimreel_gen.py` — генерація (випадкові гра, налаштування, картинки; без повторів; нові ігри з сайту);
- `stats.py` — статистика переглядів і навчання вибору;
- `history.json` — журнал (оновлюється після кожного запуску).

## Розклад
У `.github/workflows/autopost.yml` прибери `#` у рядках `schedule` — тоді публікуватиме саме (час у UTC).
