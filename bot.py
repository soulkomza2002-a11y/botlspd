import os
import nextcord
from nextcord.ext import commands, tasks
from nextcord import slash_command, Interaction
import aiohttp
import asyncio
import logging
from datetime import datetime

# ─── KONFIGURACJA ─────────────────────────────────────────────────────────────
DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN")
GUILD_ID          = int(os.getenv("GUILD_ID", "0"))
JSONBIN_BIN_ID    = os.getenv("JSONBIN_BIN_ID")
JSONBIN_API_KEY   = os.getenv("JSONBIN_API_KEY")
SYNC_INTERVAL_MIN = int(os.getenv("SYNC_INTERVAL", "5"))
LOG_CHANNEL_ID    = 1474443852784992418
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
    "Cadet":             "Cadet",
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
STATUS_SUSPENDED   = "ZAWIESZONY"
STATUS_RED_ENTRY   = "CZERWONY WPIS"
STATUS_YELLOW_ENTRY = "ŻÓŁTY WPIS"
ALL_STATUS_ROLES   = {STATUS_SUSPENDED, STATUS_RED_ENTRY, STATUS_YELLOW_ENTRY}

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
    """Zwraca najniższą wolną odznakę w przedziale dla danego stopnia, z wiodącymi zerami."""
    rng = RANK_BADGE_RANGES.get(rank)
    if not rng:
        return ""
    lo, hi = rng
    used = {int(o["badge"]) for o in officers if str(o.get("badge", "")).isdigit()}
    digits = len(str(hi))  # liczba cyfr wyznaczona przez maksimum przedziału
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

# ─── JSONBIN ──────────────────────────────────────────────────────────────────
async def fetch_officers() -> list:
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
    headers = {"X-Master-Key": JSONBIN_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    log.error(f"JSONBin HTTP {resp.status}")
                    return []
                data = await resp.json()
                return data.get("record", {}).get("officers", [])
    except Exception as e:
        log.error(f"JSONBin error: {e}")
        return []

async def fetch_full_record() -> dict:
    """Pobierz pełny rekord JSONBin (officers, log, regs, ftd, iad)."""
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
    headers = {"X-Master-Key": JSONBIN_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("record", {})
    except Exception as e:
        log.error(f"JSONBin fetch_full error: {e}")
        return {}

# ─── WATCHER AKAT IAD → DISCORD ───────────────────────────────────────────────
_known_akta_ids: set = set()
_akta_initialized: bool = False

KONSEKWENCJA_COLOR = {
    "PLUS":        0x2ecc71,
    "MINUS":       0xe74c3c,
    "ZAWIESZENIE":0xf1c40f,
    "ZWOLNIENIE":  0xff0000,
}
KONSEKWENCJA_EMOJI = {
    "PLUS":        "✅",
    "MINUS":       "❌",
    "ZAWIESZENIE": "⏸️",
    "ZWOLNIENIE":  "🔴",
}

async def check_new_akta(guild: nextcord.Guild):
    """Sprawdź czy pojawiły się nowe akta IAD i wyślij je na kanał Discord z pingiem."""
    global _known_akta_ids, _akta_initialized

    log.info(f"[IAD] check_new_akta start — guild: {guild.id}")

    record = await fetch_full_record()
    if not record:
        log.warning("[IAD] fetch_full_record zwrócił pusty rekord!")
        return

    iad    = record.get("iad", {})
    akta   = iad.get("akta", [])
    log.info(f"[IAD] Znaleziono {len(akta)} akt w JSONBin")

    current_ids = {str(a.get("id")) for a in akta}

    if not _akta_initialized:
        _known_akta_ids  = current_ids
        _akta_initialized = True
        log.info(f"[IAD] Inicjalizacja — zapamiętano {len(_known_akta_ids)} istniejących akt: {_known_akta_ids}")
        return

    new_akta = [a for a in akta if str(a.get("id")) not in _known_akta_ids]
    log.info(f"[IAD] Nowe akta: {len(new_akta)} | znane IDs: {_known_akta_ids} | current IDs: {current_ids}")

    if not new_akta:
        return

    ch = guild.get_channel(IAD_AKTA_CHANNEL_ID)
    log.info(f"[IAD] Kanał {IAD_AKTA_CHANNEL_ID}: {ch}")
    if not ch:
        log.error(f"[IAD] Kanał {IAD_AKTA_CHANNEL_ID} NIE ZNALEZIONY — sprawdź czy bot ma dostęp do kanału!")
        # Wypisz wszystkie dostępne kanały tekstowe
        text_channels = [f"{c.name}({c.id})" for c in guild.text_channels]
        log.info(f"[IAD] Dostępne kanały: {text_channels[:20]}")
        return

    # Zbuduj mapę: imię IC → member Discord (przez nick OOC z bazy officers)
    officers = record.get("officers", [])
    name_to_nick = {
        (o.get("name") or "").strip(): (o.get("nick") or "").strip().lower()
        for o in officers if o.get("name")
    }
    nick_to_member = {
        m.name.lower(): m
        for m in guild.members if not m.bot
    }

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
        log.info(f"[IAD] Akta dla: '{imie}' → OOC nick: '{ooc_nick}' → member: {member} → ping: {ping_str}")

        embed = nextcord.Embed(
            title=f"{emoji} NOWY WPIS W AKTACH IAD — {kons_label}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 Funkcjonariusz", value=imie or "—",                        inline=True)
        embed.add_field(name="⚖️ Konsekwencja",  value=kons_label,                          inline=True)
        embed.add_field(name="\u200b",            value="\u200b",                            inline=True)
        embed.add_field(name="📋 Powód",          value=akta_entry.get("powod") or "—",     inline=False)
        embed.add_field(name="✍️ Podpisał",       value=akta_entry.get("podpisal") or "—",  inline=True)
        embed.add_field(name="📅 Data",           value=akta_entry.get("data") or "—",      inline=True)
        embed.set_footer(text="LSPD IAD — System Akt")

        try:
            content = ping_str  # None jeśli nie znaleziono — Discord sam to obsłuży
            await ch.send(content=content, embed=embed)
            log.info(f"[IAD] ✅ Wysłano akte: {imie} / {kons_label} | ping: {ping_str or 'brak'}")
        except nextcord.Forbidden:
            log.error(f"[IAD] ❌ Brak uprawnień do wysłania na kanał {IAD_AKTA_CHANNEL_ID}!")
        except Exception as e:
            log.error(f"[IAD] ❌ Błąd wysyłania akty: {e}")

    _known_akta_ids = current_ids

# ─── ZAPIS DO JSONBIN ────────────────────────────────────────────────────────
async def save_officers(officers: list) -> bool:
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    headers = {"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            # Pobierz aktualne dane (log, regs) żeby nie nadpisać
            async with session.get(url + "/latest", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return False
                data = (await r.json()).get("record", {})
            data["officers"] = officers
            async with session.put(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return r.status == 200
    except Exception as e:
        log.error(f"JSONBin save error: {e}")
        return False

# ─── BUDOWANIE PSEUDONIMU ─────────────────────────────────────────────────────
def build_nickname(officer: dict) -> str:
    badge = (officer.get("badge") or "").strip()
    name  = (officer.get("name")  or "").strip()
    if badge and name:
        return f"[{badge}] {name}"
    return name or ""

# ─── SYNC LOGIC ───────────────────────────────────────────────────────────────
async def sync_roles(guild: nextcord.Guild) -> dict:
    officers = await fetch_officers()
    if not officers:
        return {"error": "Nie udało się pobrać danych z bazy"}

    # Mapa: nick OOC (nazwa konta Discord) → dane oficera
    officer_map = {}
    for o in officers:
        nick = (o.get("nick") or "").strip().lower()
        if nick:
            officer_map[nick] = o

    results = {"updated": [], "skipped": [], "not_found": [], "errors": []}
    guild_roles = {r.name: r for r in guild.roles}

    for member in guild.members:
        if member.bot:
            continue

        # Dopasowanie WYŁĄCZNIE po nazwie konta Discord (member.name)
        officer = officer_map.get(member.name.lower())

        if not officer:
            results["not_found"].append(member.name)
            continue

        rank = officer.get("rank", "")
        target_role_name = RANK_TO_ROLE.get(rank)
        target_role = guild_roles.get(target_role_name) if target_role_name else None
        if target_role_name and not target_role:
            results["errors"].append(f"Brak roli '{target_role_name}' na serwerze")

        # ── Jednostki (SWAT/IAD/FTD) ──────────────────────────────────────
        target_unit_roles = set()
        for field, role_name in UNIT_TO_ROLE.items():
            if officer.get(field):
                r = guild_roles.get(role_name)
                if r:
                    target_unit_roles.add(r)
                else:
                    results["errors"].append(f"Brak roli '{role_name}' na serwerze")

        # ── Odznaka — zmień jeśli nie pasuje do przedziału stopnia ──────
        current_badge = str(officer.get("badge") or "").strip()
        badge_changed = False
        new_badge = current_badge
        if rank in RANK_BADGE_RANGES:
            lo, hi = RANK_BADGE_RANGES[rank]
            badge_num = int(current_badge) if current_badge.isdigit() else -1
            if badge_num < lo or badge_num > hi:
                # Odznaka nie pasuje do przedziału — przydziel nową
                new_badge = assign_badge(rank, officers)
                if new_badge and new_badge != current_badge:
                    badge_changed = True

        # ── Pseudonim ──────────────────────────────────────────────────────
        # Użyj nowej odznaki do budowania pseudonimu jeśli się zmieniła
        display_officer = {**officer, "badge": new_badge} if badge_changed else officer
        target_nick  = build_nickname(display_officer)
        nick_changed = bool(target_nick) and member.display_name != target_nick

        # ── Sprawdź role stopnia ───────────────────────────────────────────
        current_lspd   = [r for r in member.roles if r.name in ALL_LSPD_ROLES]
        has_target     = any(r.name == target_role_name for r in member.roles) if target_role_name else True
        rank_to_remove = [r for r in current_lspd if r.name != target_role_name]
        rank_ok        = has_target and len(rank_to_remove) == 0

        # ── Sprawdź role jednostek ─────────────────────────────────────────
        current_unit_roles = {r for r in member.roles if r.name in ALL_UNIT_ROLES}
        units_to_add    = target_unit_roles - current_unit_roles
        units_to_remove = current_unit_roles - target_unit_roles
        units_ok        = not units_to_add and not units_to_remove

        # ── Statusy (zawieszony, wpisy) ────────────────────────────────────
        target_status_roles = set()
        if officer.get("suspended"):
            r = guild_roles.get(STATUS_SUSPENDED)
            if r:
                target_status_roles.add(r)
        if officer.get("redEntry"):
            r = guild_roles.get(STATUS_RED_ENTRY)
            if r:
                target_status_roles.add(r)
        if officer.get("yellowEntry"):
            r = guild_roles.get(STATUS_YELLOW_ENTRY)
            if r:
                target_status_roles.add(r)

        current_status_roles = {r for r in member.roles if r.name in ALL_STATUS_ROLES}
        status_to_add    = target_status_roles - current_status_roles
        status_to_remove = current_status_roles - target_status_roles
        status_ok        = not status_to_add and not status_to_remove

        # ── Command Bureau ─────────────────────────────────────────────────
        has_cb = any(r.name == "Command Bureau" for r in member.roles)
        cb_changed = bool(officer.get("commandBureau")) != has_cb
        if cb_changed:
            officer["commandBureau"] = has_cb

        if rank_ok and units_ok and status_ok and not nick_changed and not badge_changed and not cb_changed:
            results["skipped"].append(member.name)
            continue

        changes = []
        try:
            # Aktualizuj odznakę w bazie jeśli się zmieniła
            if badge_changed:
                # Zaktualizuj w liście officers od razu (żeby kolejne assign_badge w tej samej pętli widziały zajętą odznakę)
                officer["badge"] = new_badge
                changes.append(f"odznaka→#{new_badge}")

            # Aktualizuj stopień
            if not rank_ok:
                if rank_to_remove:
                    await member.remove_roles(*rank_to_remove, reason="LSPD Bot sync")
                if not has_target:
                    await member.add_roles(target_role, reason="LSPD Bot sync")
                changes.append(f"stopień→{target_role_name}")

            # Aktualizuj jednostki
            if not units_ok:
                if units_to_remove:
                    await member.remove_roles(*units_to_remove, reason="LSPD Bot sync")
                if units_to_add:
                    await member.add_roles(*units_to_add, reason="LSPD Bot sync")
                if units_to_add:
                    changes.append(f"+{','.join(r.name for r in units_to_add)}")
                if units_to_remove:
                    changes.append(f"-{','.join(r.name for r in units_to_remove)}")

            # Aktualizuj statusy
            if not status_ok:
                if status_to_remove:
                    await member.remove_roles(*status_to_remove, reason="LSPD Bot sync")
                if status_to_add:
                    await member.add_roles(*status_to_add, reason="LSPD Bot sync")
                if status_to_add:
                    changes.append(f"+{','.join(r.name for r in status_to_add)}")
                if status_to_remove:
                    changes.append(f"-{','.join(r.name for r in status_to_remove)}")

            # Aktualizuj pseudonim
            if nick_changed:
                await member.edit(nick=target_nick, reason="LSPD Bot sync")
                changes.append(f"nick→{target_nick}")

            if cb_changed:
                changes.append(f"commandBureau→{has_cb}")

            summary = f"{member.name} ({', '.join(changes)})"
            results["updated"].append(summary)
            log.info(f"[SYNC] {summary}")

        except nextcord.Forbidden:
            results["errors"].append(f"Brak uprawnień: {member.name}")
        except Exception as e:
            results["errors"].append(f"{member.name}: {e}")

    # Zapisz do JSONBin jeśli cokolwiek się zmieniło
    if any("odznaka" in u or "commandBureau" in u for u in results.get("updated", [])):
        await save_officers(officers)

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

# ── Osobny task sprawdzający akta IAD co minutę (szybka reakcja) ──────────────
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

        sent = []
        skipped = []

        for channel in category.text_channels:
            # Dopasuj po nazwie kanału (ignoruj emoji i spacje na początku)
            raw_name = channel.name.lower().strip()
            # Usuń prefix emoji jeśli jest (np. "📋-centrala" → "centrala")
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
        upd = len(results.get("updated", []))
        skip = len(results.get("skipped", []))
        nf = len(results.get("not_found", []))
        await self._log(interaction.guild, "🔄 /sync", f"**Wykonał:** {interaction.user.mention}\n✅ Zaktualizowano: **{upd}** | ⏭️ Bez zmian: **{skip}** | ❓ Nie znaleziono: **{nf}** | ⏱️ {duration:.1f}s", 0x2ecc71)

    @slash_command(name="status", description="Status bota LSPD", guild_ids=[GUILD_ID])
    async def cmd_status(self, interaction: Interaction):
        await interaction.response.defer()
        officers = await fetch_officers()
        embed = nextcord.Embed(title="🤖 LSPD Bot — Status", color=nextcord.Color.blue())
        embed.add_field(name="📡 Baza danych", value=f"{'✅ OK' if officers else '❌ Błąd'} ({len(officers)} FP)", inline=False)
        embed.add_field(name="🔄 Auto-sync",   value=f"Co {SYNC_INTERVAL_MIN} min", inline=True)
        embed.add_field(name="👥 Członków",    value=str(interaction.guild.member_count), inline=True)
        await interaction.followup.send(embed=embed)
        await self._log(interaction.guild, "📊 /status", f"**Wykonał:** {interaction.user.mention}\nBaza: {'✅ OK' if officers else '❌ Błąd'} ({len(officers)} FP)", 0x3498db)

    @slash_command(name="kto", description="Sprawdź stopień osoby w bazie LSPD", guild_ids=[GUILD_ID])
    async def cmd_kto(self, interaction: Interaction, member: nextcord.Member):
        await interaction.response.defer()
        officers = await fetch_officers()
        # /kto też szuka po nazwie konta
        found = officer_map_from(officers).get(member.name.lower())
        if not found:
            await interaction.followup.send(f"❓ **{member.name}** nie ma w bazie LSPD.", ephemeral=True)
            await self._log(interaction.guild, "🔍 /kto", f"**Wykonał:** {interaction.user.mention}\n**Szukał:** {member.mention}\n❓ Nie znaleziono w bazie", 0xe67e22)
            return
        status = "🔴 ZAWIESZONY" if found.get("suspended") else ("🟡 URLOP" if found.get("onLeave") else "🟢 AKTYWNY")
        units  = [u.upper() for u in ["swat","iad","ftd"] if found.get(u)]
        embed = nextcord.Embed(title=f"👮 {found.get('name')}", color=nextcord.Color.blue())
        embed.add_field(name="Stopień",  value=found.get("rank","—"),      inline=True)
        embed.add_field(name="Odznaka", value=f"#{found.get('badge','—')}", inline=True)
        embed.add_field(name="Status",  value=status,                       inline=True)
        if units:
            embed.add_field(name="Jednostki", value=", ".join(units), inline=False)
        await interaction.followup.send(embed=embed)
        await self._log(interaction.guild, "🔍 /kto", f"**Wykonał:** {interaction.user.mention}\n**Sprawdził:** {member.mention}\n**Wynik:** {found.get('name')} | {found.get('rank','—')} | {status}", 0x3498db)

    @slash_command(name="debug", description="Debug — szczegoly dla znalezionego usera", guild_ids=[GUILD_ID])
    async def cmd_debug(self, interaction: Interaction, member: nextcord.Member):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("Brak uprawnien.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        officers = await fetch_officers()
        omap = officer_map_from(officers)
        officer = omap.get(member.name.lower())

        if not officer:
            await interaction.followup.send(f"NIE ZNALEZIONO `{member.name}` w bazie.\nNicki w bazie: {', '.join(sorted(omap.keys()))}", ephemeral=True)
            return

        guild_roles = {r.name: r for r in interaction.guild.roles}

        rank = officer.get("rank", "")
        target_role_name = RANK_TO_ROLE.get(rank, "BRAK W MAPOWANIU")
        target_nick = build_nickname(officer)

        current_lspd = [r for r in member.roles if r.name in ALL_LSPD_ROLES]
        has_target = any(r.name == target_role_name for r in member.roles)
        rank_to_remove = [r for r in current_lspd if r.name != target_role_name]
        rank_ok = has_target and len(rank_to_remove) == 0

        current_unit_roles = {r for r in member.roles if r.name in ALL_UNIT_ROLES}
        target_unit_roles = set()
        for field, role_name in UNIT_TO_ROLE.items():
            if officer.get(field):
                r = guild_roles.get(role_name)
                if r:
                    target_unit_roles.add(r)
        units_to_add = target_unit_roles - current_unit_roles
        units_to_remove = current_unit_roles - target_unit_roles
        units_ok = not units_to_add and not units_to_remove

        nick_changed = bool(target_nick) and member.display_name != target_nick

        lines = [
            f"**Debug dla `{member.name}`**",
            f"",
            f"**Baza:**",
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
            f"**Co chce zrobic:**",
            f"  target_role: `{target_role_name}` | rank_ok: `{rank_ok}`",
            f"  target_nick: `{target_nick}` | nick_changed: `{nick_changed}`",
            f"  units_to_add: `{[r.name for r in units_to_add]}`",
            f"  units_to_remove: `{[r.name for r in units_to_remove]}`",
            f"  units_ok: `{units_ok}`",
            f"",
            f"**Wynik:** {'SKIPPED (nic do zmiany)' if rank_ok and units_ok and not nick_changed else 'POWINIEN ZMIENIC'}",
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

        omap = officer_map_from(officers)
        guild = interaction.guild
        guild_roles = {r.name: r for r in guild.roles}

        missing_mentions = []

        for member in guild.members:
            if member.bot:
                continue

            # Sprawdź czy ma jakąkolwiek rolę stopnia LSPD
            has_rank_role = any(r.name in ALL_LSPD_ROLES for r in member.roles)
            if not has_rank_role:
                continue

            # Sprawdź czy jest w bazie
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
            # Wypisz dostępne kanały żeby pomóc zdebugować
            channels_info = "\n".join(f"• `{c.name}` — `{c.id}`" for c in interaction.guild.text_channels[:30])
            await interaction.followup.send(
                f"❌ **Kanał `{IAD_AKTA_CHANNEL_ID}` nie znaleziony!**\n\n"
                f"Dostępne kanały tekstowe:\n{channels_info}",
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
            embed.add_field(name="👤 Funkcjonariusz", value="Jan Testowy",        inline=True)
            embed.add_field(name="⚖️ Konsekwencja",  value="MINUS",              inline=True)
            embed.add_field(name="📋 Powód",          value="Test systemu IAD",   inline=False)
            embed.add_field(name="✍️ Podpisał",       value="IAD Chief",          inline=True)
            embed.add_field(name="📅 Data",           value="2025-01-01",         inline=True)
            embed.set_footer(text="LSPD IAD — System Akt")
            await ch.send(content=interaction.user.mention, embed=embed)
            await interaction.followup.send(f"✅ Test wysłany na {ch.mention}!", ephemeral=True)
        except nextcord.Forbidden:
            await interaction.followup.send(
                f"❌ **Brak uprawnień do wysłania na {ch.mention}!**\n"
                f"Sprawdź czy bot ma uprawnienie `Send Messages` na tym kanale.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Błąd: `{e}`", ephemeral=True)

    @slash_command(name="iad-force-check", description="Wymuś sprawdzenie nowych akt IAD teraz", guild_ids=[GUILD_ID])
    async def cmd_iad_force_check(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        global _akta_initialized
        # Zresetuj flagę żeby wymusić ponowną inicjalizację i wykrycie nowych
        _akta_initialized = False
        await check_new_akta(interaction.guild)
        await interaction.followup.send(
            f"✅ Sprawdzono akta IAD. Znane IDs: `{len(_known_akta_ids)}`. Sprawdź logi bota po szczegóły.",
            ephemeral=True
        )
    async def cmd_przypomnienie(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj rolami**.", ephemeral=True)
            return
        await interaction.response.defer()

        officers = await fetch_officers()
        if not officers:
            await interaction.followup.send("❌ Nie udało się pobrać danych z bazy.")
            return

        omap = officer_map_from(officers)
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
            await self._log(interaction.guild, "🔔 /przypomnienie", f"**Wykonał:** {interaction.user.mention}\n🎫 Bez wpisu w bazie: **{len(no_entry_mentions)}**\n📝 Bez danych IC: **{len(no_name_mentions)}**", 0xf39c12)

def officer_map_from(officers: list) -> dict:
    return {(o.get("nick") or "").strip().lower(): o for o in officers if o.get("nick")}

WELCOME_CHANNEL_ID = 1367506926056767532

# ─── POWITANIE NOWYCH CZŁONKÓW ────────────────────────────────────────────────
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

# ─── TICKET SYSTEM ────────────────────────────────────────────────────────────
TICKET_CHANNEL_ID = 1474113895990952117

TICKET_TYPES = {
    "raport_stopien": {
        "label":       "📋 Raport o stopień",
        "description": "Złóż raport z prośbą o nadanie stopnia w LSPD.",
        "color":       0x1e5fc4,
        "roles":       [1367513692383608985],
        "channel_prefix": "raport",
    },
    "pytanie_hc": {
        "label":       "👮 Pytanie do HC",
        "description": "Zadaj pytanie do High Command LSPD.",
        "color":       0x9b59b6,
        "roles":       [1367513692383608985],
        "channel_prefix": "pytanie-hc",
    },
    "sprawa_iad": {
        "label":       "🔍 Sprawa do IAD",
        "description": "Zgłoś sprawę do Wydziału Spraw Wewnętrznych (IAD).",
        "color":       0xe74c3c,
        "roles":       [1368229314251984919, 1368227491667378288],
        "channel_prefix": "iad",
    },
    "podanie_fto": {
        "label":       "📝 Podanie na FTO",
        "description": "Złóż podanie do programu Field Training Officer.",
        "color":       0x2ecc71,
        "roles":       [1368230039971303485, 1368227491667378288],
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
            cfg = TICKET_TYPES[ticket_type]
            guild = interaction.guild

            # Sprawdź czy użytkownik już ma otwarty ticket tego typu
            channel_name = f"{cfg['channel_prefix']}-{interaction.user.id}"
            existing = nextcord.utils.get(guild.text_channels, name=channel_name)
            if existing:
                await interaction.response.send_message(
                    f"❌ Masz już otwarty ticket tego typu: {existing.mention}", ephemeral=True
                )
                return

            # Odłóż odpowiedź — tworzenie kanału może trwać ponad 3 sekundy
            await interaction.response.defer(ephemeral=True)

            # Uprawnienia kanału
            overwrites = {
                guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
                interaction.user:   nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me:           nextcord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
            }
            for role_id in cfg["roles"]:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = nextcord.PermissionOverwrite(read_messages=True, send_messages=True)

            # Kategoria — ta sama co kanał ticketów
            ticket_ch = guild.get_channel(TICKET_CHANNEL_ID)
            category = ticket_ch.category if ticket_ch else None

            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"Ticket: {cfg['label']} — {interaction.user}"
            )

            # Embed powitalny w tickecie
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

            view = CloseTicketView()
            await ticket_channel.send(content=roles_mentions, embed=embed, view=view)
            await interaction.followup.send(
                f"✅ Twój ticket został utworzony: {ticket_channel.mention}", ephemeral=True
            )

        except nextcord.Forbidden:
            log.error(f"[TICKET] Brak uprawnień — {interaction.user} / {interaction.guild}")
            try:
                await interaction.followup.send("❌ Brak uprawnień do tworzenia kanałów. Skontaktuj się z adminem.", ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            log.error(f"[TICKET] Błąd tworzenia ticketu: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"❌ Wystąpił błąd: {e}", ephemeral=True)
            except Exception:
                pass

class TicketSelectView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())

    @classmethod
    def create(cls):
        """Tworzy świeży widok do wysłania na kanał."""
        return cls()

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
        embed.set_thumbnail(url=interaction.guild.me.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket zamknięty przez {interaction.user}")

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
    # Zainicjalizuj znane akta IAD żeby nie spamować przy starcie
    guild = bot.get_guild(GUILD_ID)
    if guild:
        await check_new_akta(guild)
    await update_status()

# ─── START ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for var, val in [("DISCORD_TOKEN", DISCORD_TOKEN), ("GUILD_ID", GUILD_ID),
                     ("JSONBIN_BIN_ID", JSONBIN_BIN_ID), ("JSONBIN_API_KEY", JSONBIN_API_KEY)]:
        if not val:
            log.error(f"Brak zmiennej środowiskowej: {var}")
            exit(1)
    bot.add_cog(LSPDCog(bot))
    bot.run(DISCORD_TOKEN)
