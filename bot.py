import os
import nextcord
from nextcord.ext import commands, tasks
from nextcord import slash_command, Interaction
import aiohttp
import asyncio
import logging
from datetime import datetime

# ─── KONFIGURACJA ─────────────────────────────────────────────────────────────
DISCORD_TOKEN       = os.getenv("DISCORD_TOKEN")
GUILD_ID            = int(os.getenv("GUILD_ID", "0"))
SUPABASE_URL        = os.getenv("SUPABASE_URL", "https://gmxooidsxoqifdycqwfd.supabase.co")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdteG9vaWRzeG9xaWZkeWNxd2ZkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE4NjIxODIsImV4cCI6MjA4NzQzODE4Mn0.PhEvMKDx-dA-kmcgTvsXs4lSSRP4VDkaeh1Jf739iHs")
SYNC_INTERVAL_MIN   = int(os.getenv("SYNC_INTERVAL", "5"))
LOG_CHANNEL_ID      = 1474443852784992418
IAD_AKTA_CHANNEL_ID = 1473743212966318140

# ─── MAPOWANIE STOPIEŃ → ROLA ─────────────────────────────────────────────────
RANK_TO_ROLE = {
    "Chief of Police": "Chief of Police",
    "Assistant Chief":  "Assistant Chief",
    "Deputy Chief":     "Deputy Chief",
    "Commander":        "Commander",
    "Captain":          "Captain",
    "Lieutenant II":    "Lieutenant II",
    "Lieutenant I":     "Lieutenant I",
    "Master Sergeant":  "Master Sergeant",
    "Staff Sergeant":   "Staff Sergeant",
    "Sergeant":         "Sergeant",
    "Officer III+1":    "Officer III+1",
    "Officer III":      "Officer III",
    "Officer II":       "Officer II",
    "Officer I":        "Officer I",
    "Cadet":            "Cadet",
}
ALL_LSPD_ROLES = set(RANK_TO_ROLE.values())

# ─── MAPOWANIE JEDNOSTKI → ROLA ───────────────────────────────────────────────
UNIT_TO_ROLE = {
    "swat": "SWAT",
    "iad":  "IAD",
    "ftd":  "FTD",
    "fac":  "FAC",
    "seu":  "SEU",
    "sv":   "SV",
    "nt":   "NT",
    "pwc":  "PWC",
    "wu":   "WU",
    "k9":   "K9",
}
ALL_UNIT_ROLES = set(UNIT_TO_ROLE.values())

# ─── ROLE STATUSÓW ────────────────────────────────────────────────────────────
STATUS_SUSPENDED    = "ZAWIESZONY"
STATUS_RED_ENTRY    = "CZERWONY WPIS"
STATUS_YELLOW_ENTRY = "ŻÓŁTY WPIS"
ALL_STATUS_ROLES    = {STATUS_SUSPENDED, STATUS_RED_ENTRY, STATUS_YELLOW_ENTRY}

# ─── PRZEDZIAŁY ODZNAK ───────────────────────────────────────────────────────
RANK_BADGE_RANGES = {
    "Chief of Police": (1,   9),
    "Assistant Chief": (1,   9),
    "Deputy Chief":    (1,   9),
    "Commander":       (1,   9),
    "Captain":         (10,  19),
    "Lieutenant II":   (20,  29),
    "Lieutenant I":    (30,  39),
    "Master Sergeant": (40,  49),
    "Staff Sergeant":  (50,  59),
    "Sergeant":        (60,  69),
    "Officer III+1":   (70,  79),
    "Officer III":     (80,  99),
    "Officer II":      (100, 129),
    "Officer I":       (130, 199),
    "Cadet":           (200, 299),
}

def assign_badge(rank: str, officers: list) -> str:
    rng = RANK_BADGE_RANGES.get(rank)
    if not rng:
        return ""
    lo, hi = rng
    used = {int(o["badge"]) for o in officers if str(o.get("badge", "")).isdigit()}
    digits = len(str(hi))
    for b in range(lo, hi + 1):
        if b not in used:
            return str(b).zfill(digits)
    return ""

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("lspd-bot")

# ─── BOT ──────────────────────────────────────────────────────────────────────
intents = nextcord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─── SUPABASE — WARSTWA DANYCH ────────────────────────────────────────────────
# Baza używa JEDNEJ tabeli: lspd_data, jeden wiersz id="main"
# Cała zawartość to JSON w kolumnach: officers (list), iad (dict z .akta), ftd itp.

def _sb_headers() -> dict:
    return {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=representation",
    }

async def fetch_full_record() -> dict:
    """Pobiera pełny rekord lspd_data?id=main z Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/lspd_data?id=eq.main&select=*"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_sb_headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    log.error(f"[Supabase] fetch_full_record HTTP {resp.status}: {await resp.text()}")
                    return {}
                rows = await resp.json()
                if not rows:
                    log.error("[Supabase] fetch_full_record — brak wiersza id=main!")
                    return {}
                return rows[0]
    except Exception as e:
        log.error(f"[Supabase] fetch_full_record error: {e}")
        return {}

async def fetch_officers() -> list:
    """Zwraca listę oficerów z lspd_data.officers"""
    record = await fetch_full_record()
    officers = record.get("officers", [])
    log.info(f"[Supabase] fetch_officers — {len(officers)} oficerów")
    return officers

async def fetch_iad_akta() -> list:
    """Zwraca listę akt IAD z lspd_data.iad.akta"""
    record = await fetch_full_record()
    iad    = record.get("iad", {})
    akta   = iad.get("akta", [])
    log.info(f"[Supabase] fetch_iad_akta — {len(akta)} akt")
    return akta

async def save_full_record(data: dict) -> bool:
    """Zapisuje pełny rekord do lspd_data id=main (PATCH)."""
    url = f"{SUPABASE_URL}/rest/v1/lspd_data?id=eq.main"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.patch(url, headers=_sb_headers(), json=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                ok = resp.status in (200, 204)
                if not ok:
                    log.error(f"[Supabase] save_full_record HTTP {resp.status}: {await resp.text()}")
                return ok
    except Exception as e:
        log.error(f"[Supabase] save_full_record error: {e}")
        return False

async def update_officer(officer_id, patch: dict) -> bool:
    """Aktualizuje konkretnego oficera (po id) w tablicy officers."""
    record = await fetch_full_record()
    if not record:
        return False
    officers = record.get("officers", [])
    updated  = False
    for o in officers:
        if o.get("id") == officer_id:
            o.update(patch)
            updated = True
            break
    if not updated:
        log.warning(f"[Supabase] update_officer — nie znaleziono id={officer_id}")
        return False
    return await save_full_record({"officers": officers})

# ─── WATCHER AKAT IAD → DISCORD ───────────────────────────────────────────────
_known_akta_ids: set = set()
_akta_initialized: bool = False

KONSEKWENCJA_COLOR = {
    "PLUS":        0x2ecc71,
    "MINUS":       0xe74c3c,
    "ZAWIESZENIE": 0xf1c40f,
    "ZWOLNIENIE":  0xff0000,
}
KONSEKWENCJA_EMOJI = {
    "PLUS":        "✅",
    "MINUS":       "❌",
    "ZAWIESZENIE": "⏸️",
    "ZWOLNIENIE":  "🔴",
}

async def check_new_akta(guild: nextcord.Guild):
    global _known_akta_ids, _akta_initialized

    log.info(f"[IAD] check_new_akta start — guild: {guild.id}")

    akta = await fetch_iad_akta()
    if not akta and not _akta_initialized:
        log.warning("[IAD] fetch_iad_akta zwrócił pustą listę!")

    current_ids = {str(a.get("id")) for a in akta}

    if not _akta_initialized:
        _known_akta_ids  = current_ids
        _akta_initialized = True
        log.info(f"[IAD] Inicjalizacja — zapamiętano {len(_known_akta_ids)} istniejących akt")
        return

    new_akta = [a for a in akta if str(a.get("id")) not in _known_akta_ids]
    log.info(f"[IAD] Nowe akta: {len(new_akta)}")

    if not new_akta:
        return

    ch = guild.get_channel(IAD_AKTA_CHANNEL_ID)
    if not ch:
        log.error(f"[IAD] Kanał {IAD_AKTA_CHANNEL_ID} nie znaleziony!")
        return

    # Mapa imię IC → member Discord
    officers = await fetch_officers()
    name_to_nick = {
        (o.get("name") or "").strip(): (o.get("nick") or "").strip().lower()
        for o in officers if o.get("name")
    }
    nick_to_member = {m.name.lower(): m for m in guild.members if not m.bot}

    for akta_entry in new_akta:
        konsekwencja = akta_entry.get("konsekwencja", "MINUS")
        czas         = akta_entry.get("zawieszenieCzas", "")
        kons_label   = konsekwencja + (f" — {czas}" if konsekwencja == "ZAWIESZENIE" and czas else "")
        color        = KONSEKWENCJA_COLOR.get(konsekwencja, 0x888888)
        emoji        = KONSEKWENCJA_EMOJI.get(konsekwencja, "📁")
        imie         = (akta_entry.get("imieNazwisko") or "").strip()

        ooc_nick = name_to_nick.get(imie, "")
        member   = nick_to_member.get(ooc_nick) if ooc_nick else None
        ping_str = member.mention if member else None
        log.info(f"[IAD] Akta dla: '{imie}' → OOC nick: '{ooc_nick}' → ping: {ping_str}")

        embed = nextcord.Embed(
            title=f"{emoji} NOWY WPIS W AKTACH IAD — {kons_label}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 Funkcjonariusz", value=imie or "—",                       inline=True)
        embed.add_field(name="⚖️ Konsekwencja",  value=kons_label,                         inline=True)
        embed.add_field(name="\u200b",            value="\u200b",                           inline=True)
        embed.add_field(name="📋 Powód",          value=akta_entry.get("powod") or "—",    inline=False)
        embed.add_field(name="✍️ Podpisał",       value=akta_entry.get("podpisal") or "—", inline=True)
        embed.add_field(name="📅 Data",           value=akta_entry.get("data") or "—",     inline=True)
        embed.set_footer(text="LSPD IAD — System Akt")

        try:
            await ch.send(content=ping_str, embed=embed)
            log.info(f"[IAD] ✅ Wysłano akte: {imie} / {kons_label}")
        except nextcord.Forbidden:
            log.error(f"[IAD] ❌ Brak uprawnień do wysłania na kanał {IAD_AKTA_CHANNEL_ID}!")
        except Exception as e:
            log.error(f"[IAD] ❌ Błąd wysyłania akty: {e}")

    _known_akta_ids = current_ids

# ─── BUDOWANIE PSEUDONIMU ─────────────────────────────────────────────────────
def build_nickname(officer: dict) -> str:
    badge = (officer.get("badge") or "").strip()
    name  = (officer.get("name")  or "").strip()
    if badge and name:
        return f"[{badge}] {name}"
    return name or ""

def officer_map_from(officers: list) -> dict:
    return {(o.get("nick") or "").strip().lower(): o for o in officers if o.get("nick")}

# ─── SYNC LOGIC ───────────────────────────────────────────────────────────────
async def sync_roles(guild: nextcord.Guild) -> dict:
    record = await fetch_full_record()
    if not record:
        return {"error": "Nie udało się pobrać danych z Supabase"}
    officers = record.get("officers", [])
    if not officers:
        return {"error": "Brak oficerów w bazie (officers jest pusty)"}

    officer_map = officer_map_from(officers)
    results = {"updated": [], "skipped": [], "not_found": [], "errors": []}
    guild_roles = {r.name: r for r in guild.roles}
    db_dirty = False  # czy trzeba zapisać zmiany do Supabase

    for member in guild.members:
        if member.bot:
            continue

        officer = officer_map.get(member.name.lower())
        if not officer:
            results["not_found"].append(member.name)
            continue

        rank            = officer.get("rank", "")
        target_role_name = RANK_TO_ROLE.get(rank)
        target_role      = guild_roles.get(target_role_name) if target_role_name else None
        if target_role_name and not target_role:
            results["errors"].append(f"Brak roli '{target_role_name}' na serwerze")

        # ── Jednostki ─────────────────────────────────────────────────────────
        target_unit_roles = set()
        for field, role_name in UNIT_TO_ROLE.items():
            if officer.get(field):
                r = guild_roles.get(role_name)
                if r:
                    target_unit_roles.add(r)
                else:
                    results["errors"].append(f"Brak roli '{role_name}' na serwerze")

        # ── Odznaka ───────────────────────────────────────────────────────────
        current_badge = str(officer.get("badge") or "").strip()
        badge_changed = False
        new_badge     = current_badge
        if rank in RANK_BADGE_RANGES:
            lo, hi    = RANK_BADGE_RANGES[rank]
            badge_num = int(current_badge) if current_badge.isdigit() else -1
            if badge_num < lo or badge_num > hi:
                new_badge = assign_badge(rank, officers)
                if new_badge and new_badge != current_badge:
                    badge_changed = True

        # ── Pseudonim ─────────────────────────────────────────────────────────
        display_officer = {**officer, "badge": new_badge} if badge_changed else officer
        target_nick  = build_nickname(display_officer)
        nick_changed = bool(target_nick) and member.display_name != target_nick

        # ── Role stopnia ──────────────────────────────────────────────────────
        current_lspd   = [r for r in member.roles if r.name in ALL_LSPD_ROLES]
        has_target     = any(r.name == target_role_name for r in member.roles) if target_role_name else True
        rank_to_remove = [r for r in current_lspd if r.name != target_role_name]
        rank_ok        = has_target and len(rank_to_remove) == 0

        # ── Role jednostek ────────────────────────────────────────────────────
        current_unit_roles = {r for r in member.roles if r.name in ALL_UNIT_ROLES}
        units_to_add    = target_unit_roles - current_unit_roles
        units_to_remove = current_unit_roles - target_unit_roles
        units_ok        = not units_to_add and not units_to_remove

        # ── Statusy ───────────────────────────────────────────────────────────
        target_status_roles = set()
        if officer.get("suspended"):
            r = guild_roles.get(STATUS_SUSPENDED)
            if r: target_status_roles.add(r)
        if officer.get("redEntry"):
            r = guild_roles.get(STATUS_RED_ENTRY)
            if r: target_status_roles.add(r)
        if officer.get("yellowEntry"):
            r = guild_roles.get(STATUS_YELLOW_ENTRY)
            if r: target_status_roles.add(r)

        current_status_roles = {r for r in member.roles if r.name in ALL_STATUS_ROLES}
        status_to_add    = target_status_roles - current_status_roles
        status_to_remove = current_status_roles - target_status_roles
        status_ok        = not status_to_add and not status_to_remove

        # ── Command Bureau ────────────────────────────────────────────────────
        has_cb    = any(r.name == "Command Bureau" for r in member.roles)
        cb_changed = bool(officer.get("commandBureau")) != has_cb

        if rank_ok and units_ok and status_ok and not nick_changed and not badge_changed and not cb_changed:
            results["skipped"].append(member.name)
            continue

        changes = []
        try:
            if badge_changed:
                officer["badge"] = new_badge
                officer["_bot_patched"] = True  # oznacz do bezpiecznego zapisu
                db_dirty = True
                changes.append(f"odznaka→#{new_badge}")

            if not rank_ok:
                if rank_to_remove:
                    await member.remove_roles(*rank_to_remove, reason="LSPD Bot sync")
                if not has_target and target_role:
                    await member.add_roles(target_role, reason="LSPD Bot sync")
                changes.append(f"stopień→{target_role_name}")

            if not units_ok:
                if units_to_remove:
                    await member.remove_roles(*units_to_remove, reason="LSPD Bot sync")
                if units_to_add:
                    await member.add_roles(*units_to_add, reason="LSPD Bot sync")
                if units_to_add:
                    changes.append(f"+{','.join(r.name for r in units_to_add)}")
                if units_to_remove:
                    changes.append(f"-{','.join(r.name for r in units_to_remove)}")

            if not status_ok:
                if status_to_remove:
                    await member.remove_roles(*status_to_remove, reason="LSPD Bot sync")
                if status_to_add:
                    await member.add_roles(*status_to_add, reason="LSPD Bot sync")
                if status_to_add:
                    changes.append(f"+{','.join(r.name for r in status_to_add)}")
                if status_to_remove:
                    changes.append(f"-{','.join(r.name for r in status_to_remove)}")

            if nick_changed:
                await member.edit(nick=target_nick, reason="LSPD Bot sync")
                changes.append(f"nick→{target_nick}")

            if cb_changed:
                officer["commandBureau"] = has_cb
                officer["_bot_patched"] = True  # oznacz do bezpiecznego zapisu
                db_dirty = True
                changes.append(f"commandBureau→{has_cb}")

            summary = f"{member.name} ({', '.join(changes)})"
            results["updated"].append(summary)
            log.info(f"[SYNC] {summary}")

        except nextcord.Forbidden:
            results["errors"].append(f"Brak uprawnień: {member.name}")
        except Exception as e:
            results["errors"].append(f"{member.name}: {e}")

    # Zapisz zmiany odznak do Supabase — BEZPIECZNY sposób:
    # Pobieramy ŚWIEŻY rekord tuż przed zapisem, nakładamy tylko zmiany odznak/commandBureau
    # i zapisujemy. Dzięki temu nie nadpisujemy zmian wprowadzonych przez panel webowy.
    if db_dirty:
        # Zbierz tylko zmiany które bot chce zapisać (id → patch)
        badge_patches = {}
        for o in officers:
            if "_bot_patched" in o:
                badge_patches[o["id"]] = {k: v for k, v in o.items() if k != "_bot_patched"}

        # Pobierz świeży rekord z Supabase
        fresh_record = await fetch_full_record()
        if fresh_record:
            fresh_officers = fresh_record.get("officers", [])
            # Nałóż tylko zmiany odznak/commandBureau na świeże dane
            for fo in fresh_officers:
                patch = badge_patches.get(fo.get("id"))
                if patch:
                    fo["badge"]         = patch.get("badge",         fo.get("badge"))
                    fo["commandBureau"] = patch.get("commandBureau", fo.get("commandBureau"))
            ok = await save_full_record({"officers": fresh_officers})
            if ok:
                log.info(f"[SYNC] Zapisano zmiany odznak do Supabase (świeży rekord, {len(badge_patches)} zmian)")
            else:
                log.error(f"[SYNC] Błąd zapisu do Supabase!")
                results["errors"].append("Błąd zapisu zmian do Supabase")
        else:
            log.error(f"[SYNC] Nie udało się pobrać świeżego rekordu przed zapisem — pominięto zapis")
            results["errors"].append("Nie udało się pobrać świeżego rekordu do zapisu odznak")

    return results

# ─── EMBEDS ───────────────────────────────────────────────────────────────────
def build_embeds(results: dict, duration: float) -> list:
    color   = nextcord.Color.green() if not results.get("errors") else nextcord.Color.orange()
    updated = results.get("updated", [])
    skipped = results.get("skipped", [])
    nf      = results.get("not_found", [])
    errors  = results.get("errors", [])

    embed = nextcord.Embed(title="🔄 LSPD — Synchronizacja ról", color=color, timestamp=datetime.utcnow())
    embed.set_footer(text=f"Czas: {duration:.1f}s")
    embed.add_field(name="✅ Zaktualizowano", value=str(len(updated)), inline=True)
    embed.add_field(name="⏭️ Bez zmian",     value=str(len(skipped)), inline=True)
    embed.add_field(name="❓ Nie znaleziono", value=str(len(nf)),      inline=True)
    if errors:
        embed.add_field(name="❌ Błędy", value="\n".join(errors[:5]) + ("..." if len(errors) > 5 else ""), inline=False)

    embeds = [embed]
    if updated:
        desc = "\n".join(f"• {u}" for u in updated[:20])
        if len(updated) > 20:
            desc += f"\n... i {len(updated)-20} więcej"
        embeds.append(nextcord.Embed(title="📋 Lista zmian", description=desc, color=nextcord.Color.blue()))

    return embeds

# ─── AUTO-SYNC ────────────────────────────────────────────────────────────────
@tasks.loop(minutes=SYNC_INTERVAL_MIN)
async def auto_sync():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    t = asyncio.get_event_loop().time()
    results = await sync_roles(guild)
    duration = asyncio.get_event_loop().time() - t
    upd = len(results.get("updated", []))
    log.info(f"[AUTO-SYNC] {upd} zmian, {len(results.get('errors',[]))} błędów, {duration:.1f}s")
    if LOG_CHANNEL_ID and upd > 0:
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if ch:
            for e in build_embeds(results, duration):
                await ch.send(embed=e)
    await update_status()

@auto_sync.before_loop
async def before_auto_sync():
    await bot.wait_until_ready()

@tasks.loop(minutes=1)
async def iad_akta_watch():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        await check_new_akta(guild)

@iad_akta_watch.before_loop
async def before_iad_watch():
    await bot.wait_until_ready()

async def update_status():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    count = sum(1 for m in guild.members if not m.bot)
    await bot.change_presence(activity=nextcord.Activity(
        type=nextcord.ActivityType.watching,
        name=f"{count} funkcjonariuszy LSPD"
    ))

# ─── SZABLONY CENTRALI ────────────────────────────────────────────────────────
CENTRALA_CATEGORY_ID = 1473743014076874904

CENTRALA_TEMPLATES = {
    "centrala": (
        "📢 **WEZWANIE DO BIURA!**\n\n"
        "**Kto wzywa:**\n"
        "**Kogo:**\n"
        "**Powód:**"
    ),
    "akta": (
        "📁 **SZABLON AKTA**\n\n"
        "**Funkcjonariusz:**\n"
        "**Stopień:**\n"
        "**Odznaka:**\n"
        "**Nick OOC:**\n"
        "**Data wpisu:**\n"
        "**Treść:**\n"
        "**Wystawił:**"
    ),
    "awanse": (
        "⬆️ **SZABLON AWANSU**\n\n"
        "**Kto nadaje:**\n"
        "**Kto otrzymuje:**\n"
        "**Stary stopień:**\n"
        "**Nowy stopień:**\n"
        "**Powód:**"
    ),
    "degradacje": (
        "⬇️ **SZABLON DEGRADACJI**\n\n"
        "**Kto nadaje:**\n"
        "**Kto otrzymuje:**\n"
        "**Stary stopień:**\n"
        "**Nowy stopień:**\n"
        "**Powód:**"
    ),
    "zwolnienia": (
        "🔴 **SZABLON ZWOLNIENIA**\n\n"
        "**Kto zwalnia:**\n"
        "**Kto zostaje zwolniony:**\n"
        "**Stopień:**\n"
        "**Powód:**\n"
        "**Data:**"
    ),
    "zawieszenia": (
        "⏸️ **SZABLON ZAWIESZENIA**\n\n"
        "**Kto zawiesza:**\n"
        "**Kto zostaje zawieszony:**\n"
        "**Stopień:**\n"
        "**Powód:**\n"
        "**Okres zawieszenia:**\n"
        "**Data:**"
    ),
    "urlopy": (
        "🏖️ **SZABLON URLOPU**\n\n"
        "**Funkcjonariusz:**\n"
        "**Stopień:**\n"
        "**Powód:**\n"
        "**Okres urlopu (od — do):**"
    ),
    "wypowiedzenia": (
        "🚪 **SZABLON WYPOWIEDZENIA**\n\n"
        "**Funkcjonariusz:**\n"
        "**Stopień:**\n"
        "**Powód rezygnacji:**\n"
        "**Data:**"
    ),
}

# ─── COG Z KOMENDAMI ──────────────────────────────────────────────────────────
class LSPDCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _log(self, guild: nextcord.Guild, title: str, description: str, color: int):
        if not LOG_CHANNEL_ID:
            return
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if not ch:
            return
        embed = nextcord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
        embed.set_footer(text="LSPD Bot")
        try:
            await ch.send(embed=embed)
        except Exception as e:
            log.error(f"Log channel send error: {e}")

    @slash_command(name="centrala-setup", description="Wysyła szablony na wszystkie kanały kategorii Centrala", guild_ids=[GUILD_ID])
    async def cmd_centrala_setup(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        category = interaction.guild.get_channel(CENTRALA_CATEGORY_ID)
        if not category or not isinstance(category, nextcord.CategoryChannel):
            await interaction.followup.send("❌ Nie znaleziono kategorii Centrala.", ephemeral=True)
            return

        sent    = []
        skipped = []

        for channel in category.text_channels:
            raw_name   = channel.name.lower().strip()
            clean_name = raw_name.lstrip("📋📁⬆️⬇️🔴⏸️🏖️🚪-| ").strip()

            template = None
            for key in CENTRALA_TEMPLATES:
                if key in clean_name or clean_name in key:
                    template = CENTRALA_TEMPLATES[key]
                    break

            if not template:
                skipped.append(channel.name)
                continue

            try:
                await channel.send(template)
                sent.append(channel.name)
            except nextcord.Forbidden:
                skipped.append(f"{channel.name} (brak uprawnień)")

        result = f"✅ Wysłano szablony na **{len(sent)}** kanałów: {', '.join(sent) or '—'}"
        if skipped:
            result += f"\n⚠️ Pominięto: {', '.join(skipped)}"
        await interaction.followup.send(result, ephemeral=True)

    @slash_command(name="sync", description="Ręczna synchronizacja ról i pseudonimów LSPD", guild_ids=[GUILD_ID])
    async def cmd_sync(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj rolami**.", ephemeral=True)
            return
        await interaction.response.defer()
        t = asyncio.get_event_loop().time()
        results = await sync_roles(interaction.guild)
        duration = asyncio.get_event_loop().time() - t
        if "error" in results:
            await interaction.followup.send(f"❌ {results['error']}")
            await self._log(interaction.guild, "🔄 /sync", f"**Wykonał:** {interaction.user.mention}\n❌ Błąd: {results['error']}", 0xe74c3c)
            return
        for embed in build_embeds(results, duration):
            await interaction.followup.send(embed=embed)
        upd  = len(results.get("updated", []))
        skip = len(results.get("skipped", []))
        nf   = len(results.get("not_found", []))
        await self._log(interaction.guild, "🔄 /sync", f"**Wykonał:** {interaction.user.mention}\n✅ Zaktualizowano: **{upd}** | ⏭️ Bez zmian: **{skip}** | ❓ Nie znaleziono: **{nf}** | ⏱️ {duration:.1f}s", 0x2ecc71)

    @slash_command(name="status", description="Status bota LSPD", guild_ids=[GUILD_ID])
    async def cmd_status(self, interaction: Interaction):
        await interaction.response.defer()
        officers = await fetch_officers()
        embed = nextcord.Embed(title="🤖 LSPD Bot — Status", color=nextcord.Color.blue())
        embed.add_field(name="📡 Baza danych", value=f"{'✅ Supabase OK' if officers else '❌ Błąd Supabase'} ({len(officers)} FP)", inline=False)
        embed.add_field(name="🔄 Auto-sync",   value=f"Co {SYNC_INTERVAL_MIN} min", inline=True)
        embed.add_field(name="👥 Członków",    value=str(interaction.guild.member_count), inline=True)
        await interaction.followup.send(embed=embed)
        await self._log(interaction.guild, "📊 /status", f"**Wykonał:** {interaction.user.mention}\nBaza: {'✅ OK' if officers else '❌ Błąd'} ({len(officers)} FP)", 0x3498db)

    @slash_command(name="kto", description="Sprawdź stopień osoby w bazie LSPD", guild_ids=[GUILD_ID])
    async def cmd_kto(self, interaction: Interaction, member: nextcord.Member):
        await interaction.response.defer()
        officers = await fetch_officers()
        found = officer_map_from(officers).get(member.name.lower())
        if not found:
            await interaction.followup.send(f"❓ **{member.name}** nie ma w bazie LSPD.", ephemeral=True)
            await self._log(interaction.guild, "🔍 /kto", f"**Wykonał:** {interaction.user.mention}\n**Szukał:** {member.mention}\n❓ Nie znaleziono w bazie", 0xe67e22)
            return
        status = "🔴 ZAWIESZONY" if found.get("suspended") else ("🟡 URLOP" if found.get("onLeave") else "🟢 AKTYWNY")
        units  = [u.upper() for u in ["swat","iad","ftd"] if found.get(u)]
        embed  = nextcord.Embed(title=f"👮 {found.get('name')}", color=nextcord.Color.blue())
        embed.add_field(name="Stopień",  value=found.get("rank","—"),       inline=True)
        embed.add_field(name="Odznaka", value=f"#{found.get('badge','—')}", inline=True)
        embed.add_field(name="Status",  value=status,                        inline=True)
        if units:
            embed.add_field(name="Jednostki", value=", ".join(units), inline=False)
        await interaction.followup.send(embed=embed)
        await self._log(interaction.guild, "🔍 /kto", f"**Wykonał:** {interaction.user.mention}\n**Sprawdził:** {member.mention}\n**Wynik:** {found.get('name')} | {found.get('rank','—')} | {status}", 0x3498db)

    @slash_command(name="debug", description="Debug — szczegóły dla znalezionego usera", guild_ids=[GUILD_ID])
    async def cmd_debug(self, interaction: Interaction, member: nextcord.Member):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("Brak uprawnień.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        officers = await fetch_officers()
        omap     = officer_map_from(officers)
        officer  = omap.get(member.name.lower())

        if not officer:
            await interaction.followup.send(f"NIE ZNALEZIONO `{member.name}` w bazie.\nNicki w bazie: {', '.join(sorted(omap.keys()))}", ephemeral=True)
            return

        guild_roles = {r.name: r for r in interaction.guild.roles}

        rank             = officer.get("rank", "")
        target_role_name = RANK_TO_ROLE.get(rank, "BRAK W MAPOWANIU")
        target_nick      = build_nickname(officer)

        current_lspd    = [r for r in member.roles if r.name in ALL_LSPD_ROLES]
        has_target      = any(r.name == target_role_name for r in member.roles)
        rank_to_remove  = [r for r in current_lspd if r.name != target_role_name]
        rank_ok         = has_target and len(rank_to_remove) == 0

        current_unit_roles = {r for r in member.roles if r.name in ALL_UNIT_ROLES}
        target_unit_roles  = set()
        for field, role_name in UNIT_TO_ROLE.items():
            if officer.get(field):
                r = guild_roles.get(role_name)
                if r:
                    target_unit_roles.add(r)
        units_to_add    = target_unit_roles - current_unit_roles
        units_to_remove = current_unit_roles - target_unit_roles
        units_ok        = not units_to_add and not units_to_remove

        nick_changed = bool(target_nick) and member.display_name != target_nick

        lines = [
            f"**Debug dla `{member.name}`**",
            f"",
            f"**Baza (Supabase):**",
            f"  nick: `{officer.get('nick')}`",
            f"  name: `{officer.get('name')}`",
            f"  badge: `{officer.get('badge')}`",
            f"  rank: `{rank}`",
            f"  swat: `{officer.get('swat')}` | iad: `{officer.get('iad')}` | ftd: `{officer.get('ftd')}`",
            f"",
            f"**Discord:**",
            f"  member.name: `{member.name}`",
            f"  display_name: `{member.display_name}`",
            f"  role stopnia: `{[r.name for r in current_lspd]}`",
            f"  role jednostek: `{[r.name for r in current_unit_roles]}`",
            f"",
            f"**Co chce zrobić:**",
            f"  target_role: `{target_role_name}` | rank_ok: `{rank_ok}`",
            f"  target_nick: `{target_nick}` | nick_changed: `{nick_changed}`",
            f"  units_to_add: `{[r.name for r in units_to_add]}`",
            f"  units_to_remove: `{[r.name for r in units_to_remove]}`",
            f"  units_ok: `{units_ok}`",
            f"",
            f"**Wynik:** {'SKIPPED (nic do zmiany)' if rank_ok and units_ok and not nick_changed else 'POWINIEN ZMIENIĆ'}",
        ]

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @slash_command(name="helper", description="Pinguje osoby z rolą stopnia LSPD, których nie ma w bazie", guild_ids=[GUILD_ID])
    async def cmd_helper(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj rolami**.", ephemeral=True)
            return
        await interaction.response.defer()

        officers = await fetch_officers()
        if not officers:
            await interaction.followup.send("❌ Nie udało się pobrać danych z bazy.")
            return

        omap  = officer_map_from(officers)
        guild = interaction.guild

        missing_mentions = []
        for member in guild.members:
            if member.bot:
                continue
            has_rank_role = any(r.name in ALL_LSPD_ROLES for r in member.roles)
            if not has_rank_role:
                continue
            if omap.get(member.name.lower()) is None:
                missing_mentions.append(member.mention)

        if missing_mentions:
            await interaction.channel.send(
                f"**⚠️ Posiadają rolę stopnia, ale nie ma ich w bazie LSPD:**\n{', '.join(missing_mentions)}"
            )
            await interaction.followup.send(
                f"✅ Znaleziono **{len(missing_mentions)}** osób z rolą stopnia bez wpisu w bazie.",
                ephemeral=True
            )
            await self._log(interaction.guild, "⚠️ /helper", f"**Wykonał:** {interaction.user.mention}\nZnaleziono **{len(missing_mentions)}** osób z rolą stopnia bez wpisu w bazie.", 0xe67e22)
        else:
            await interaction.followup.send("✅ Wszystkie osoby z rolami stopni są w bazie.", ephemeral=True)
            await self._log(interaction.guild, "⚠️ /helper", f"**Wykonał:** {interaction.user.mention}\n✅ Wszyscy z rolami stopni są w bazie.", 0x2ecc71)

    # ─── NAPRAWIONA KOMENDA /przypomnienie ────────────────────────────────────
    @slash_command(name="przypomnienie", description="Pinguje osoby bez wpisu w bazie lub bez danych IC", guild_ids=[GUILD_ID])
    async def cmd_przypomnienie(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj rolami**.", ephemeral=True)
            return
        await interaction.response.defer()

        officers = await fetch_officers()
        if not officers:
            await interaction.followup.send("❌ Nie udało się pobrać danych z bazy.")
            return

        omap  = officer_map_from(officers)
        guild = interaction.guild

        no_entry_mentions = []
        no_name_mentions  = []

        for member in guild.members:
            if member.bot:
                continue
            officer = omap.get(member.name.lower())
            if officer is None:
                no_entry_mentions.append(member.mention)
            else:
                name_field = (officer.get("name") or "").strip()
                if not name_field:
                    no_name_mentions.append(member.mention)

        if no_entry_mentions:
            await interaction.channel.send(
                f"**🎫 Stwórz ticket z raportem o stopień:**\n{', '.join(no_entry_mentions)}"
            )
        if no_name_mentions:
            await interaction.channel.send(
                f"**📝 Ustaw dane IC jako pseudonim!**\n{', '.join(no_name_mentions)}"
            )

        if not no_entry_mentions and not no_name_mentions:
            await interaction.followup.send("✅ Wszyscy członkowie mają kompletne dane w bazie.", ephemeral=True)
            await self._log(interaction.guild, "🔔 /przypomnienie", f"**Wykonał:** {interaction.user.mention}\n✅ Wszyscy mają kompletne dane.", 0x2ecc71)
        else:
            await interaction.followup.send(
                f"✅ Wysłano przypomnienia: **{len(no_entry_mentions)}** bez wpisu w bazie, **{len(no_name_mentions)}** bez danych IC.",
                ephemeral=True
            )
            await self._log(interaction.guild, "🔔 /przypomnienie", f"**Wykonał:** {interaction.user.mention}\n🎫 Bez wpisu: **{len(no_entry_mentions)}** | 📝 Bez IC: **{len(no_name_mentions)}**", 0xf39c12)

    @slash_command(name="ticket-setup", description="Wysyła panel ticketów na kanał", guild_ids=[GUILD_ID])
    async def cmd_ticket_setup(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(TICKET_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Nie znaleziono kanału ticketów.", ephemeral=True)
            return

        embed = nextcord.Embed(
            title="🎫 SYSTEM TICKETÓW — LSPD",
            description=(
                "Witaj w systemie zgłoszeń Los Santos Police Department.\n\n"
                "Wybierz rodzaj sprawy z listy poniżej, aby otworzyć prywatny ticket "
                "z odpowiednim personelem LSPD.\n\n"
                "**Dostępne kategorie:**\n"
                "📋 **Raport o stopień** — nadanie stopnia w LSPD\n"
                "👮 **Pytanie do HC** — kontakt z High Command\n"
                "🔍 **Sprawa do IAD** — Wydział Spraw Wewnętrznych\n"
                "📝 **Podanie na FTO** — program Field Training Officer\n\n"
                "*Pamiętaj — otwieraj ticket tylko w uzasadnionych przypadkach.*"
            ),
            color=0x1e5fc4,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.me.display_avatar.url)
        embed.set_footer(text="Los Santos Police Department · Ticket System")

        await channel.send(embed=embed, view=TicketSelectView())
        await interaction.response.send_message(f"✅ Panel ticketów wysłany na {channel.mention}.", ephemeral=True)

    @slash_command(name="iad-test", description="Test wysyłania akty IAD na kanał", guild_ids=[GUILD_ID])
    async def cmd_iad_test(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        ch = interaction.guild.get_channel(IAD_AKTA_CHANNEL_ID)
        if not ch:
            channels_info = "\n".join(f"• `{c.name}` — `{c.id}`" for c in interaction.guild.text_channels[:30])
            await interaction.followup.send(
                f"❌ **Kanał `{IAD_AKTA_CHANNEL_ID}` nie znaleziony!**\n\nDostępne kanały:\n{channels_info}",
                ephemeral=True
            )
            return

        try:
            embed = nextcord.Embed(
                title="🧪 TEST — NOWY WPIS W AKTACH IAD",
                description="To jest wiadomość testowa systemu IAD.",
                color=0xe74c3c,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="👤 Funkcjonariusz", value="Jan Testowy",       inline=True)
            embed.add_field(name="⚖️ Konsekwencja",  value="MINUS",             inline=True)
            embed.add_field(name="📋 Powód",          value="Test systemu IAD",  inline=False)
            embed.add_field(name="✍️ Podpisał",       value="IAD Chief",         inline=True)
            embed.add_field(name="📅 Data",           value="2025-01-01",        inline=True)
            embed.set_footer(text="LSPD IAD — System Akt")
            await ch.send(content=interaction.user.mention, embed=embed)
            await interaction.followup.send(f"✅ Test wysłany na {ch.mention}!", ephemeral=True)
        except nextcord.Forbidden:
            await interaction.followup.send(f"❌ **Brak uprawnień do wysłania na {ch.mention}!**", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd: `{e}`", ephemeral=True)

    @slash_command(name="iad-force-check", description="Wymuś sprawdzenie nowych akt IAD teraz", guild_ids=[GUILD_ID])
    async def cmd_iad_force_check(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        global _akta_initialized
        _akta_initialized = False
        await check_new_akta(interaction.guild)
        await interaction.followup.send(
            f"✅ Sprawdzono akta IAD. Znane IDs: `{len(_known_akta_ids)}`. Sprawdź logi po szczegóły.",
            ephemeral=True
        )

# ─── TICKET SYSTEM ────────────────────────────────────────────────────────────
TICKET_CHANNEL_ID = 1474113895990952117

TICKET_TYPES = {
    "raport_stopien": {
        "label":          "📋 Raport o stopień",
        "description":    "Złóż raport z prośbą o nadanie stopnia w LSPD.",
        "color":          0x1e5fc4,
        "roles":          [1367513692383608985],
        "channel_prefix": "raport",
    },
    "pytanie_hc": {
        "label":          "👮 Pytanie do HC",
        "description":    "Zadaj pytanie do High Command LSPD.",
        "color":          0x9b59b6,
        "roles":          [1367513692383608985],
        "channel_prefix": "pytanie-hc",
    },
    "sprawa_iad": {
        "label":          "🔍 Sprawa do IAD",
        "description":    "Zgłoś sprawę do Wydziału Spraw Wewnętrznych (IAD).",
        "color":          0xe74c3c,
        "roles":          [1368229314251984919, 1368227491667378288],
        "channel_prefix": "iad",
    },
    "podanie_fto": {
        "label":          "📝 Podanie na FTO",
        "description":    "Złóż podanie do programu Field Training Officer.",
        "color":          0x2ecc71,
        "roles":          [1368230039971303485, 1368227491667378288],
        "channel_prefix": "fto",
    },
}

class TicketTypeSelect(nextcord.ui.Select):
    def __init__(self):
        options = [
            nextcord.SelectOption(label=v["label"], value=k, description=v["description"])
            for k, v in TICKET_TYPES.items()
        ]
        super().__init__(
            placeholder="Wybierz rodzaj ticketu...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="persistent_ticket_select"
        )

    async def callback(self, interaction: Interaction):
        try:
            ticket_type = self.values[0]
            cfg         = TICKET_TYPES[ticket_type]
            guild       = interaction.guild

            channel_name = f"{cfg['channel_prefix']}-{interaction.user.id}"
            existing     = nextcord.utils.get(guild.text_channels, name=channel_name)
            if existing:
                await interaction.response.send_message(
                    f"❌ Masz już otwarty ticket tego typu: {existing.mention}", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)

            overwrites = {
                guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
                interaction.user:   nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me:           nextcord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
            }
            for role_id in cfg["roles"]:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = nextcord.PermissionOverwrite(read_messages=True, send_messages=True)

            ticket_ch = guild.get_channel(TICKET_CHANNEL_ID)
            category  = ticket_ch.category if ticket_ch else None

            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"Ticket: {cfg['label']} — {interaction.user}"
            )

            embed = nextcord.Embed(
                title=cfg["label"],
                description=(
                    f"Witaj {interaction.user.mention}!\n\n"
                    f"{cfg['description']}\n\n"
                    f"Opisz swoją sprawę jak najdokładniej. "
                    f"Odpowiedni personel zajmie się Twoim zgłoszeniem wkrótce.\n\n"
                    f"Aby zamknąć ticket użyj przycisku poniżej."
                ),
                color=cfg["color"],
                timestamp=datetime.utcnow()
            )
            embed.set_thumbnail(url=guild.me.display_avatar.url)
            embed.set_footer(text="LSPD Ticket System")

            roles_mentions = " ".join(f"<@&{r}>" for r in cfg["roles"])
            view           = CloseTicketView()
            await ticket_channel.send(content=roles_mentions, embed=embed, view=view)
            await interaction.followup.send(f"✅ Twój ticket: {ticket_channel.mention}", ephemeral=True)

        except nextcord.Forbidden:
            log.error(f"[TICKET] Brak uprawnień — {interaction.user}")
            try:
                await interaction.followup.send("❌ Brak uprawnień do tworzenia kanałów.", ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            log.error(f"[TICKET] Błąd: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"❌ Błąd: {e}", ephemeral=True)
            except Exception:
                pass

class TicketSelectView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())

    async def on_error(self, error: Exception, interaction: Interaction) -> None:
        log.error(f"[TICKET SELECT ERROR] {error}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Błąd: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Błąd: {error}", ephemeral=True)
        except Exception:
            pass

class CloseTicketView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="🔒 Zamknij ticket", style=nextcord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, button: nextcord.ui.Button, interaction: Interaction):
        embed = nextcord.Embed(
            title="🔒 Ticket zamknięty",
            description=f"Ticket zamknięty przez {interaction.user.mention}.\nKanał zostanie usunięty za 5 sekund.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket zamknięty przez {interaction.user}")

# ─── POWITANIE NOWYCH CZŁONKÓW ────────────────────────────────────────────────
WELCOME_CHANNEL_ID = 1367506926056767532

@bot.event
async def on_member_join(member: nextcord.Member):
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        return

    embed = nextcord.Embed(
        title="🚔 NOWY REKRUT W SZEREGACH LSPD",
        description=(
            f"**{member.mention}** właśnie dołączył do Los Santos Police Department.\n\n"
            f"Witamy Cię w strukturach jednej z najbardziej prestiżowych formacji w Los Santos. "
            f"Przed Tobą długa droga — od Kadeta aż po szczyty hierarchii.\n\n"
            f"📋 **Pierwsze kroki:**\n"
            f"• Zapoznaj się z regulaminem serwera\n"
            f"• Stwórz ticket i złóż raport o stopień\n"
            f"• Ustaw swój pseudonim jako **[Odznaka] Imię Nazwisko IC**\n\n"
            f"*Stróżuj z honorem. Służ z oddaniem.*"
        ),
        color=0x1e5fc4,
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=member.guild.me.display_avatar.url)
    embed.set_footer(text=f"Los Santos Police Department · Członek #{member.guild.member_count}")

    await channel.send(embed=embed)
    await update_status()

# ─── ON READY ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"✅ Bot online: {bot.user} | Serwer: {GUILD_ID} | Sync co {SYNC_INTERVAL_MIN} min")
    bot.add_view(TicketSelectView())
    bot.add_view(CloseTicketView())
    if not auto_sync.is_running():
        auto_sync.start()
    if not iad_akta_watch.is_running():
        iad_akta_watch.start()
    guild = bot.get_guild(GUILD_ID)
    if guild:
        await check_new_akta(guild)
    await update_status()

# ─── START ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    missing = []
    for var, val in [
        ("DISCORD_TOKEN", DISCORD_TOKEN),
        ("GUILD_ID",      GUILD_ID),
        ("SUPABASE_URL",  SUPABASE_URL),
        ("SUPABASE_KEY",  SUPABASE_KEY),
    ]:
        if not val:
            missing.append(var)
    if missing:
        for m in missing:
            log.error(f"Brak zmiennej środowiskowej: {m}")
        exit(1)
    bot.add_cog(LSPDCog(bot))
    bot.run(DISCORD_TOKEN)
