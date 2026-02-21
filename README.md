# 🤖 LSPD Discord Bot — Instrukcja Setup

Bot automatycznie nadaje role na Discord na podstawie stopni z bazy danych LSPD.

---

## KROK 1 — Stwórz aplikację bota na Discord

1. Wejdź na https://discord.com/developers/applications
2. Kliknij **New Application** → wpisz nazwę (np. `LSPD Bot`)
3. Przejdź do zakładki **Bot** → kliknij **Add Bot**
4. Skopiuj **TOKEN** (przycisk "Reset Token") — będzie potrzebny później
5. Włącz te opcje pod "Privileged Gateway Intents":
   - ✅ **SERVER MEMBERS INTENT**
   - ✅ **MESSAGE CONTENT INTENT**

## KROK 2 — Dodaj bota na serwer

1. Przejdź do zakładki **OAuth2 → URL Generator**
2. Zaznacz scope: `bot` + `applications.commands`
3. Zaznacz uprawnienia bota:
   - ✅ Manage Roles
   - ✅ Send Messages
   - ✅ View Channels
4. Skopiuj wygenerowany URL i otwórz go w przeglądarce
5. Dodaj bota na swój serwer

## KROK 3 — Pobierz ID serwera

1. Na Discordzie: Ustawienia → Zaawansowane → włącz **Tryb dewelopera**
2. Kliknij PPM na nazwę swojego serwera → **Kopiuj identyfikator serwera**

## KROK 4 — Utwórz role na serwerze Discord

Utwórz role o **dokładnie takich nazwach** (wielkość liter ma znaczenie!):
```
Chief of Police
Assistant Chief
Deputy Chief
Commander
Captain
Lieutenant II
Lieutenant I
Master Sergeant
Staff Sergeant
Sergeant
Officer III+1
Officer III
Officer II
Officer I
```
⚠️ **Rola bota musi być WYŻEJ niż wszystkie role LSPD** na liście ról serwera!

## KROK 5 — Deploy na Railway (darmowy)

1. Wejdź na https://railway.app i zaloguj się przez GitHub
2. Kliknij **New Project → Deploy from GitHub repo**
3. Wgraj pliki `bot.py` i `requirements.txt` na GitHub (lub użyj Upload)
4. W Railway kliknij na swój projekt → **Variables** → dodaj:

| Zmienna | Wartość |
|---------|---------|
| `DISCORD_TOKEN` | Token bota z Kroku 1 |
| `GUILD_ID` | ID serwera z Kroku 3 |
| `JSONBIN_BIN_ID` | `6998859343b1c97be98eb84c` |
| `JSONBIN_API_KEY` | `$2a$10$3L8S1mGNReuQXCj1pvYGaeUH0o1HosE59kmJC6exDhU.1aVPMY0fy` |
| `SYNC_INTERVAL` | `5` (minuty, możesz zmienić) |
| `LOG_CHANNEL_ID` | ID kanału na logi (opcjonalne, wpisz `0` żeby wyłączyć) |

5. Railway automatycznie wykryje `requirements.txt` i uruchomi bota

---

## Jak działa dopasowanie użytkowników?

Bot porównuje **nick OOC** z bazy danych z:
- **Nazwą użytkownika Discord** (`username`)
- **Wyświetlaną nazwą na serwerze** (`display name / server nick`)

Porównanie jest **bez uwzględnienia wielkości liter**.

**Przykład:**
- W bazie nick OOC: `soulek`
- Na Discordzie username: `Soulek` lub nick na serwerze: `soulek` → ✅ Match

---

## Komendy slash

| Komenda | Opis | Uprawnienia |
|---------|------|-------------|
| `/sync` | Ręczna synchronizacja ról | Manage Roles |
| `/status` | Status bota i połączenia | Wszyscy |
| `/kto @user` | Sprawdź stopień osoby w bazie | Wszyscy |

---

## Częste problemy

**Bot nie nadaje ról:**
- Sprawdź czy rola bota jest wyżej niż role LSPD na liście ról serwera
- Sprawdź czy nazwy ról na Discordzie są identyczne jak w `RANK_TO_ROLE` w `bot.py`

**"Nie znaleziono użytkownika":**
- Nick OOC w bazie musi pasować do username lub nick na serwerze Discord
- Porównanie jest case-insensitive (wielkość liter nie ma znaczenia)

**Zmiana interwału auto-sync:**
- Zmień zmienną `SYNC_INTERVAL` w Railway na inną liczbę minut
