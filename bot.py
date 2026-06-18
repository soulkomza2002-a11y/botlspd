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
LOG_CHANNEL_ID         = 1474443852784992418
IAD_AKTA_CHANNEL_ID    = 1473743212966318140
AWANS_CHANNEL_ID       = 1473743256650121308
DEGRADACJA_CHANNEL_ID  = 1473743274094231734

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
    "swat": "METRO",
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

# ─── PRZEDZIAŁY ODZNAK (LSPD) ────────────────────────────────────────────────
RANK_BADGE_RANGES = {
    "Chief of Police": (1,   9),
    "Assistant Chief": (1,   9),
    "Deputy Chief":    (1,   9),
    "Commander":       (1,   9),
    "Captain":         (6,   19),
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

# ─── BCSO — MAPOWANIE STOPIEŃ → ROLA (po ID, nie po nazwie) ──────────────────
RANK_ROLE_IDS_BCSO = {
    "Sheriff":          1491929649968840725,
    "Undersheriff":     1491929649968840725,
    "Captain":          1491930224798072832,
    "Lieutenant II":    1491930221547491500,
    "Lieutenant I":     1491930217881669652,
    "Sergeant III":     1491930210399031316,
    "Sergeant II":      1491930189930823813,
    "Sergeant I":       1491930125762039918,
    "Corporal":         1491930086528520332,
    "Deputy III":       1491930009223561436,
    "Deputy II":        1491929829333794877,
    "Deputy I":         1491929649968840725,
}
RANK_BADGE_RANGES_BCSO = {
    "Sheriff":          (401, 401),
    "Undersheriff":     (402, 402),
    "Captain":          (405, 409),
    "Lieutenant II":    (410, 419),
    "Lieutenant I":     (420, 429),
    "Sergeant III":     (430, 439),
    "Sergeant II":      (440, 449),
    "Sergeant I":       (450, 459),
    "Corporal":         (460, 469),
    "Deputy III":       (470, 479),
    "Deputy II":        (480, 489),
    "Deputy I":         (490, 499),
}

# ─── FIB — MAPOWANIE STOPIEŃ → ROLA (po ID) ──────────────────────────────────
RANK_ROLE_IDS_FIB = {
    "Director of FIB": 1488604232675233852,
    "Special Agent":   1488604426267529227,
    "Agent":           1488604472677629952,
}
RANK_BADGE_RANGES_FIB = {
    "Director of FIB": (701, 704),
    "Special Agent":   (705, 710),
    "Agent":           (720, 730),
}

# ─── BAZOWA ROLA JEDNOSTKI (BCSO/FIB — LSPD nie ma osobnej roli bazowej) ─────
DEPT_ROLE_IDS = {
    "BCSO": 1491181892458774699,
    "FIB":  1491934461628252170,
}

ALL_BCSO_RANK_ROLE_IDS = set(RANK_ROLE_IDS_BCSO.values())
ALL_FIB_RANK_ROLE_IDS  = set(RANK_ROLE_IDS_FIB.values())
ALL_DEPT_BASE_ROLE_IDS = set(DEPT_ROLE_IDS.values())

def rank_badge_ranges_for_dept(dept: str) -> dict:
    if dept == "BCSO":
        return RANK_BADGE_RANGES_BCSO
    if dept == "FIB":
        return RANK_BADGE_RANGES_FIB
    return RANK_BADGE_RANGES

def assign_badge(rank: str, officers: list, dept: str = "LSPD") -> str:
    ranges = rank_badge_ranges_for_dept(dept)
    rng = ranges.get(rank)
    if not rng:
        return ""
    lo, hi = rng
    used = {
        int(o["badge"]) for o in officers
        if (o.get("dept") or "LSPD") == dept and str(o.get("badge", "")).isdigit()
    }
    digits = len(str(hi))
    for b in range(lo, hi + 1):
        if b not in used:
            return str(b).zfill(digits)
    return ""

def get_target_role(guild, dept: str, rank: str, guild_roles_by_name: dict):
    """Zwraca (obiekt_roli, nazwa_roli) dla danego dept+rank. BCSO/FIB po ID, LSPD po nazwie."""
    if dept == "BCSO":
        role_id = RANK_ROLE_IDS_BCSO.get(rank)
        role = guild.get_role(role_id) if role_id else None
        return role, (role.name if role else None)
    if dept == "FIB":
        role_id = RANK_ROLE_IDS_FIB.get(rank)
        role = guild.get_role(role_id) if role_id else None
        return role, (role.name if role else None)
    role_name = RANK_TO_ROLE.get(rank)
    role = guild_roles_by_name.get(role_name) if role_name else None
    return role, role_name

def all_rank_role_objects(guild, guild_roles_by_name: dict) -> set:
    """Wszystkie role 'stopnia' z każdej jednostki — do wykrywania nieaktualnych ról po zmianie dept/rangi."""
    roles = set()
    for name in ALL_LSPD_ROLES:
        r = guild_roles_by_name.get(name)
        if r:
            roles.add(r)
    for rid in ALL_BCSO_RANK_ROLE_IDS | ALL_FIB_RANK_ROLE_IDS:
        r = guild.get_role(rid)
        if r:
            roles.add(r)
    return roles


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

# ─── KOLEJNOŚĆ STOPNI ────────────────────────────────────────────────────────
RANK_ORDER_BOT = [
    "Cadet", "Officer I", "Officer II", "Officer III", "Officer III+1",
    "Sergeant", "Staff Sergeant", "Master Sergeant",
    "Lieutenant I", "Lieutenant II",
    "Captain", "Commander", "Deputy Chief", "Assistant Chief", "Chief of Police"
]

# ─── WATCHER OGŁOSZEŃ AWANSÓW / DEGRADACJI ───────────────────────────────────
# Panel webowy zapisuje pendingAnnounce do oficera w Supabase.
# Bot co minutę sprawdza czy ktoś ma tę flagę, wysyła embed z member.mention
# i czyści flagę żeby nie wysłać drugi raz.

# Zbiór ID oficerów, które są aktualnie przetwarzane — zapobiega podwójnemu wysłaniu
# jeśli bot sprawdzi Supabase zanim zdąży wyczyścić flagę z poprzedniego cyklu.
_pending_in_progress: set = set()

async def process_pending_announces(guild: nextcord.Guild):
    global _pending_in_progress

    record = await fetch_full_record()
    if not record:
        return
    officers = record.get("officers", [])

    # Filtruj tylko tych, którzy mają flagę I nie są już przetwarzani w tym cyklu
    pending = [
        o for o in officers
        if o.get("pendingAnnounce") and o.get("id") not in _pending_in_progress
    ]
    if not pending:
        return

    log.info(f"[ANNOUNCE] Znaleziono {len(pending)} oczekujących ogłoszeń")

    # Zablokuj te ID natychmiast — zanim cokolwiek wyślemy
    newly_processing = {o["id"] for o in pending}
    _pending_in_progress |= newly_processing

    # Mapa nick → member
    nick_to_member = {m.name.lower(): m for m in guild.members if not m.bot}

    sent_ids = set()

    for officer in pending:
        ann       = officer["pendingAnnounce"]
        old_rank  = ann.get("oldRank", "—")
        new_rank  = ann.get("newRank", "—")
        old_badge = ann.get("oldBadge", "")
        new_badge = ann.get("newBadge", "")
        ann_type  = ann.get("type", "AWANS")
        reason    = ann.get("reason", "").strip()

        is_promotion = ann_type == "AWANS"
        channel_id   = AWANS_CHANNEL_ID if is_promotion else DEGRADACJA_CHANNEL_ID
        channel      = guild.get_channel(channel_id)
        if not channel:
            log.warning(f"[ANNOUNCE] Kanał {channel_id} nie znaleziony!")
            sent_ids.add(officer["id"])
            continue

        name  = officer.get("name", "—")
        nick  = (officer.get("nick") or "").strip().lower()
        color = 0x2ecc71 if is_promotion else 0xe74c3c
        emoji = "⬆️" if is_promotion else "⬇️"
        label = "AWANS" if is_promotion else "DEGRADACJA"

        member = nick_to_member.get(nick)
        ping   = member.mention if member else f"@{officer.get('nick', name)}"

        embed = nextcord.Embed(
            title=f"{emoji} {label} — {name}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 Funkcjonariusz",    value=name or "—",                              inline=True)
        embed.add_field(name="🔖 Nick OOC",          value=officer.get("nick") or "—",               inline=True)
        embed.add_field(name="\u200b",               value="\u200b",                                  inline=True)
        embed.add_field(name="📉 Poprzedni stopień", value=old_rank,                                  inline=True)
        embed.add_field(name="📈 Nowy stopień",      value=new_rank,                                  inline=True)
        embed.add_field(name="\u200b",               value="\u200b",                                  inline=True)
        embed.add_field(name="🪪 Stara odznaka",     value=f"#{old_badge}" if old_badge else "—",    inline=True)
        embed.add_field(name="🆕 Nowa odznaka",      value=f"#{new_badge}" if new_badge else "—",    inline=True)
        embed.add_field(name="\u200b",               value="\u200b",                                  inline=True)
        if reason:
            embed.add_field(name="📝 Powód",         value=reason,                                    inline=False)
        embed.set_footer(text="LSPD — System zarządzania")

        try:
            await channel.send(content=ping, embed=embed)
            log.info(f"[ANNOUNCE] ✅ {label}: {name} ({old_rank}→{new_rank}) #{old_badge}→#{new_badge} | ping: {ping}")
        except Exception as e:
            log.error(f"[ANNOUNCE] ❌ Błąd wysyłania: {e}")

        # Oznacz jako wysłane niezależnie od sukcesu — żeby nie spamować
        sent_ids.add(officer["id"])

    if sent_ids:
        # Pobierz ŚWIEŻY rekord i wyczyść tylko flagi już wysłanych
        fresh = await fetch_full_record()
        if fresh:
            fresh_officers = fresh.get("officers", [])
            cleared = 0
            for fo in fresh_officers:
                if fo.get("id") in sent_ids and fo.get("pendingAnnounce"):
                    fo.pop("pendingAnnounce", None)
                    cleared += 1
            ok = await save_full_record({"officers": fresh_officers})
            if ok:
                log.info(f"[ANNOUNCE] Wyczyszczono pendingAnnounce dla {cleared} oficerów")
            else:
                log.error("[ANNOUNCE] Błąd zapisu po wyczyszczeniu pendingAnnounce")
        else:
            log.error("[ANNOUNCE] Nie udało się pobrać świeżego rekordu — flagi nie wyczyszczone")

        # Zwolnij blokadę dopiero po udanym zapisie
        _pending_in_progress -= sent_ids

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
    all_rank_roles = all_rank_role_objects(guild, guild_roles)  # role stopnia z każdej jednostki
    db_dirty = False  # czy trzeba zapisać zmiany do Supabase

    for member in guild.members:
        if member.bot:
            continue

        officer = officer_map.get(member.name.lower())
        if not officer:
            results["not_found"].append(member.name)
            continue

        dept              = (officer.get("dept") or "LSPD").strip() or "LSPD"
        rank              = officer.get("rank", "")
        target_role, target_role_name = get_target_role(guild, dept, rank, guild_roles)
        if target_role_name and not target_role:
            results["errors"].append(f"Brak roli '{target_role_name}' na serwerze ({dept})")

        # ── Jednostki ─────────────────────────────────────────────────────────
        target_unit_roles = set()
        for field, role_name in UNIT_TO_ROLE.items():
            val = officer.get(field)
            # Jawna obsługa swat → METRO z logiem diagnostycznym
            if field == "swat":
                log.info(f"[METRO] {member.name} — officer[swat]={val!r}")
                if val:
                    r = guild_roles.get("METRO")
                    if r:
                        target_unit_roles.add(r)
                        log.info(f"[METRO] ✅ Dodano rolę METRO dla {member.name}")
                    else:
                        results["errors"].append("Brak roli 'METRO' na serwerze Discord!")
                        log.error("[METRO] ❌ Rola 'METRO' nie istnieje na serwerze!")
                continue
            if val:
                r = guild_roles.get(role_name)
                if r:
                    target_unit_roles.add(r)
                else:
                    results["errors"].append(f"Brak roli '{role_name}' na serwerze")

        # ── Odznaka ───────────────────────────────────────────────────────────
        current_badge  = str(officer.get("badge") or "").strip()
        badge_changed   = False
        new_badge       = current_badge
        badge_ranges    = rank_badge_ranges_for_dept(dept)
        if rank in badge_ranges:
            lo, hi    = badge_ranges[rank]
            badge_num = int(current_badge) if current_badge.isdigit() else -1
            if badge_num < lo or badge_num > hi:
                new_badge = assign_badge(rank, officers, dept)
                if new_badge and new_badge != current_badge:
                    badge_changed = True

        # ── Pseudonim ─────────────────────────────────────────────────────────
        display_officer = {**officer, "badge": new_badge} if badge_changed else officer
        target_nick  = build_nickname(display_officer)
        nick_changed = bool(target_nick) and member.display_name != target_nick

        # ── Role stopnia (LSPD/BCSO/FIB) ─────────────────────────────────────
        current_rank_roles = [r for r in member.roles if r in all_rank_roles]
        has_target     = (target_role in member.roles) if target_role else True
        rank_to_remove = [r for r in current_rank_roles if r != target_role]
        rank_ok        = has_target and len(rank_to_remove) == 0

        # ── Bazowa rola jednostki (BCSO/FIB — LSPD nie ma osobnej roli) ──────
        target_dept_role = None
        if dept in DEPT_ROLE_IDS:
            target_dept_role = guild.get_role(DEPT_ROLE_IDS[dept])
            if not target_dept_role:
                results["errors"].append(f"Brak bazowej roli jednostki dla '{dept}' na serwerze")
        current_dept_roles = [r for r in member.roles if r.id in ALL_DEPT_BASE_ROLE_IDS]
        has_dept_role  = (target_dept_role in member.roles) if target_dept_role else True
        dept_to_remove = [r for r in current_dept_roles if r != target_dept_role]
        dept_ok        = has_dept_role and len(dept_to_remove) == 0

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

        if rank_ok and dept_ok and units_ok and status_ok and not nick_changed and not badge_changed and not cb_changed:
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

            if not dept_ok:
                if dept_to_remove:
                    await member.remove_roles(*dept_to_remove, reason="LSPD Bot sync")
                if not has_dept_role and target_dept_role:
                    await member.add_roles(target_dept_role, reason="LSPD Bot sync")
                changes.append(f"jednostka→{dept}")

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

ZWOLNIENIA_CHANNEL_ID = 1473743297288868025   # kanał zwolnień
FIRED_KEEP_ROLE_ID    = 1473730397425897695   # jedyna rola która zostaje

async def process_pending_fire(guild: nextcord.Guild):
    """Sprawdza pendingFire w Supabase i wysyła ogłoszenia zwolnień z pingiem."""
    record = await fetch_full_record()
    if not record:
        return
    pending = record.get("pendingFire", [])
    if not pending:
        return

    log.info(f"[FIRE] Znaleziono {len(pending)} oczekujących zwolnień")

    channel = guild.get_channel(ZWOLNIENIA_CHANNEL_ID)
    if not channel:
        log.warning(f"[FIRE] Kanał {ZWOLNIENIA_CHANNEL_ID} nie znaleziony!")

    nick_to_member = {m.name.lower(): m for m in guild.members if not m.bot}
    keep_role      = guild.get_role(FIRED_KEEP_ROLE_ID)

    for entry in pending:
        name   = entry.get("name",   "—")
        nick   = (entry.get("nick") or "").strip().lower()
        badge  = entry.get("badge",  "")
        rank   = entry.get("rank",   "—")
        reason = entry.get("reason", "").strip()

        member = nick_to_member.get(nick)
        ping   = member.mention if member else f"@{entry.get('nick', name)}"

        # ── Resetuj pseudonim i role ──────────────────────────────────────────
        if member:
            # 1. Reset pseudonimu (nick → None = przywraca nazwę użytkownika)
            try:
                await member.edit(nick=None, reason=f"LSPD Bot — zwolnienie: {name}")
                log.info(f"[FIRE] Reset pseudonimu: {member.name}")
            except Exception as e:
                log.warning(f"[FIRE] Nie można zresetować pseudonimu {member.name}: {e}")

            # 2. Wyczyść wszystkie role LSPD — zostaw tylko FIRED_KEEP_ROLE_ID
            roles_to_remove = [
                r for r in member.roles
                if r.name != "@everyone"
                and r.id != FIRED_KEEP_ROLE_ID
            ]
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason=f"LSPD Bot — zwolnienie: {name}")
                    log.info(f"[FIRE] Usunięto {len(roles_to_remove)} ról dla {member.name}")
                except Exception as e:
                    log.warning(f"[FIRE] Nie można usunąć ról {member.name}: {e}")

            # 3. Upewnij się że ma rolę "zostaje"
            if keep_role and keep_role not in member.roles:
                try:
                    await member.add_roles(keep_role, reason=f"LSPD Bot — zwolnienie: {name}")
                    log.info(f"[FIRE] Dodano rolę {keep_role.name} dla {member.name}")
                except Exception as e:
                    log.warning(f"[FIRE] Nie można dodać roli {keep_role.name} dla {member.name}: {e}")

        # ── Wyślij embed na kanał ─────────────────────────────────────────────
        if channel:
            embed = nextcord.Embed(
                title="🔴 ZWOLNIENIE — " + name,
                color=0xe74c3c,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="👤 Funkcjonariusz", value=name,                              inline=True)
            embed.add_field(name="🔖 Nick OOC",       value=entry.get("nick") or "—",         inline=True)
            embed.add_field(name="\u200b",            value="\u200b",                           inline=True)
            embed.add_field(name="🪪 Odznaka",        value=f"#{badge}" if badge else "—",    inline=True)
            embed.add_field(name="📋 Stopień",        value=rank,                              inline=True)
            embed.add_field(name="\u200b",            value="\u200b",                           inline=True)
            if reason:
                embed.add_field(name="📝 Powód",      value=reason,                            inline=False)
            embed.set_footer(text="LSPD — System zarządzania")

            try:
                await channel.send(content=ping, embed=embed)
                log.info(f"[FIRE] ✅ Zwolnienie wysłane: {name} ({nick}) | ping: {ping}")
            except Exception as e:
                log.error(f"[FIRE] ❌ Błąd wysyłania: {e}")

    # Wyczyść pendingFire po wysłaniu
    ok = await save_full_record({"pendingFire": []})
    if ok:
        log.info(f"[FIRE] Wyczyszczono pendingFire ({len(pending)} wpisów)")
    else:
        log.error("[FIRE] Błąd czyszczenia pendingFire")


@tasks.loop(minutes=1)
async def announce_watch():
    guild = bot.get_guild(GUILD_ID)
    if guild:
        await process_pending_announces(guild)
        await process_pending_fire(guild)

@announce_watch.before_loop
async def before_announce_watch():
    await bot.wait_until_ready()

# ─── SYSTEM URLOPOWY ──────────────────────────────────────────────────────────
URLOP_PANEL_CHANNEL_ID   = 1480776929077497897   # kanał z guzikiem
URLOP_WNIOSKI_CHANNEL_ID = 1480776372170522694   # kanał z wnioskami do akceptacji

# Modal z formularzem urlopowym
class UrlopModal(nextcord.ui.Modal):
    def __init__(self):
        super().__init__(title="📋 Wniosek o urlop", timeout=300)

        self.imie = nextcord.ui.TextInput(
            label="Imię i Nazwisko (IC)",
            placeholder="np. John Kowalski",
            required=True,
            max_length=100,
        )
        self.powod = nextcord.ui.TextInput(
            label="Powód",
            placeholder="Podaj powód urlopu...",
            style=nextcord.TextInputStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.start = nextcord.ui.TextInput(
            label="Rozpoczęcie [dzień/miesiąc/rok]",
            placeholder="np. 15/06/2025",
            required=True,
            max_length=20,
        )
        self.end = nextcord.ui.TextInput(
            label="Zakończenie [dzień/miesiąc/rok]",
            placeholder="np. 22/06/2025",
            required=True,
            max_length=20,
        )

        self.add_item(self.imie)
        self.add_item(self.powod)
        self.add_item(self.start)
        self.add_item(self.end)

    async def callback(self, interaction: nextcord.Interaction):
        channel = interaction.guild.get_channel(URLOP_WNIOSKI_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Nie znaleziono kanału wniosków.", ephemeral=True)
            return

        embed = nextcord.Embed(
            title="🏖️ WNIOSEK O URLOP",
            color=0x3498db,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 Imię i Nazwisko",      value=self.imie.value,  inline=True)
        embed.add_field(name="🔖 Nick OOC",             value=interaction.user.mention, inline=True)
        embed.add_field(name="\u200b",                  value="\u200b",         inline=True)
        embed.add_field(name="📋 Powód",                value=self.powod.value, inline=False)
        embed.add_field(name="📅 Rozpoczęcie",          value=self.start.value, inline=True)
        embed.add_field(name="📅 Zakończenie",          value=self.end.value,   inline=True)
        embed.set_footer(text=f"Złożony przez: {interaction.user.name} • ID: {interaction.user.id}")

        msg = await channel.send(
            embed=embed,
            view=UrlopDecisionView(
                officer_name=self.imie.value,
                end_date_str=self.end.value,
                applicant_id=interaction.user.id,
            )
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        await interaction.response.send_message(
            "✅ Twój wniosek o urlop został złożony! Poczekaj na decyzję przełożonych.",
            ephemeral=True
        )
        log.info(f"[URLOP] Wniosek złożony: {self.imie.value} ({interaction.user.name}) | {self.start.value} — {self.end.value}")

# Widok panelu z guzikiem "Wniosek o urlop" i "Obecny urlop"
class UrlopPanelView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(
        label="🏖️  Wniosek o urlop",
        style=nextcord.ButtonStyle.primary,
        custom_id="urlop_wniosek_btn"
    )
    async def urlop_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(UrlopModal())

    @nextcord.ui.button(
        label="📋  Obecny urlop",
        style=nextcord.ButtonStyle.secondary,
        custom_id="urlop_obecny_btn"
    )
    async def obecny_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Znajdź urlop użytkownika w bazie
        record = await fetch_full_record()
        if not record:
            await interaction.response.send_message("❌ Błąd połączenia z bazą danych.", ephemeral=True)
            return

        officers = record.get("officers", [])
        officer = None
        for o in officers:
            if str(o.get("discordId") or "") == str(interaction.user.id):
                officer = o
                break
        # Fallback po nicku
        if not officer:
            for o in officers:
                if (o.get("nick") or "").strip().lower() == interaction.user.name.lower():
                    officer = o
                    break

        if not officer or not officer.get("onLeave"):
            await interaction.response.send_message(
                "ℹ️ Nie jesteś aktualnie na urlopie lub nie znaleziono Cię w bazie.",
                ephemeral=True
            )
            return

        end_date = officer.get("leaveEndDate", "—")
        name = officer.get("name", "—")

        embed = nextcord.Embed(
            title="📋 TWÓJ OBECNY URLOP",
            color=0x3498db,
            description=f"**{name}** — urlop aktywny do **{end_date}**"
        )
        await interaction.response.send_message(
            embed=embed,
            view=UrlopObecnyView(officer_name=name, end_date=end_date, applicant_id=interaction.user.id),
            ephemeral=True
        )


# Widok z przyciskami "Zakończ urlop" i "Edytuj urlop"
class UrlopObecnyView(nextcord.ui.View):
    def __init__(self, officer_name: str = "", end_date: str = "", applicant_id: int = 0):
        super().__init__(timeout=120)
        self.officer_name = officer_name
        self.end_date = end_date
        self.applicant_id = applicant_id

    @nextcord.ui.button(label="🔴  Zakończ urlop", style=nextcord.ButtonStyle.danger, custom_id="urlop_zakoncz_btn")
    async def zakoncz_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        # Znajdź i zaktualizuj oficera w bazie
        record = await fetch_full_record()
        if not record:
            await interaction.response.send_message("❌ Błąd połączenia z bazą danych.", ephemeral=True)
            return

        officers = record.get("officers", [])
        officer = None
        for o in officers:
            if str(o.get("discordId") or "") == str(interaction.user.id):
                officer = o
                break
        if not officer:
            for o in officers:
                if (o.get("nick") or "").strip().lower() == interaction.user.name.lower():
                    officer = o
                    break

        if not officer:
            await interaction.response.send_message("❌ Nie znaleziono Cię w bazie.", ephemeral=True)
            return

        old_end = officer.get("leaveEndDate", "—")
        officer["onLeave"] = False
        officer["leaveEndDate"] = ""
        officer["leaveStartDate"] = ""
        ok = await save_full_record({"officers": officers})
        if not ok:
            await interaction.response.send_message("❌ Błąd zapisu do bazy danych.", ephemeral=True)
            return

        # Wyślij powiadomienie na kanał wniosków
        channel = interaction.guild.get_channel(URLOP_WNIOSKI_CHANNEL_ID)
        if channel:
            embed = nextcord.Embed(
                title="🔴 PRZEDWCZESNE ZAKOŃCZENIE URLOPU",
                color=0xe74c3c,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="👤 Funkcjonariusz", value=officer.get("name", "—"), inline=True)
            embed.add_field(name="🔖 Nick OOC", value=interaction.user.mention, inline=True)
            embed.add_field(name="📅 Urlop miał trwać do", value=old_end, inline=True)
            embed.set_footer(text=f"Zakończono przez: {interaction.user.name} • ID: {interaction.user.id}")
            await channel.send(embed=embed)

        await interaction.response.send_message(
            "✅ Twój urlop został przedwcześnie zakończony. Status zmieniony na **Aktywny**.",
            ephemeral=True
        )
        log.info(f"[URLOP] 🔴 Przedwczesne zakończenie: {officer.get('name')} ({interaction.user.name}) | było do {old_end}")

    @nextcord.ui.button(label="✏️  Edytuj urlop", style=nextcord.ButtonStyle.primary, custom_id="urlop_edytuj_btn")
    async def edytuj_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(
            UrlopEdytujModal(
                officer_name=self.officer_name,
                current_end=self.end_date,
                applicant_id=self.applicant_id
            )
        )


# Modal edycji urlopu
class UrlopEdytujModal(nextcord.ui.Modal):
    def __init__(self, officer_name: str = "", current_end: str = "", applicant_id: int = 0):
        super().__init__(title="✏️ Edycja urlopu", timeout=300)
        self.officer_name = officer_name
        self.applicant_id = applicant_id

        self.new_end = nextcord.ui.TextInput(
            label="Nowa data zakończenia [dzień/miesiąc/rok]",
            placeholder=f"Obecna: {current_end}",
            default_value=current_end,
            required=True,
            max_length=20,
        )
        self.powod = nextcord.ui.TextInput(
            label="Powód zmiany",
            placeholder="Dlaczego zmieniasz datę zakończenia?",
            style=nextcord.TextInputStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.new_end)
        self.add_item(self.powod)

    async def callback(self, interaction: nextcord.Interaction):
        channel = interaction.guild.get_channel(URLOP_WNIOSKI_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Nie znaleziono kanału wniosków.", ephemeral=True)
            return

        embed = nextcord.Embed(
            title="✏️ WNIOSEK O EDYCJĘ URLOPU",
            color=0xf39c12,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="👤 Imię i Nazwisko", value=self.officer_name, inline=True)
        embed.add_field(name="🔖 Nick OOC", value=interaction.user.mention, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="📅 Nowa data zakończenia", value=self.new_end.value, inline=True)
        embed.add_field(name="📋 Powód zmiany", value=self.powod.value, inline=False)
        embed.set_footer(text=f"Złożony przez: {interaction.user.name} • ID: {interaction.user.id}")

        await channel.send(
            embed=embed,
            view=UrlopEdycjaDecisionView(
                officer_name=self.officer_name,
                new_end_date=self.new_end.value,
                applicant_id=interaction.user.id,
            )
        )

        await interaction.response.send_message(
            "✅ Wniosek o edycję urlopu został wysłany. Poczekaj na decyzję przełożonych.",
            ephemeral=True
        )
        log.info(f"[URLOP] ✏️ Wniosek o edycję: {self.officer_name} ({interaction.user.name}) | nowa data: {self.new_end.value}")


# Widok decyzji edycji urlopu (Akceptuj / Odrzuć)
class UrlopEdycjaDecisionView(nextcord.ui.View):
    def __init__(self, officer_name: str = "", new_end_date: str = "", applicant_id: int = 0):
        super().__init__(timeout=None)
        self.officer_name = officer_name
        self.new_end_date = new_end_date
        self.applicant_id = applicant_id

    @nextcord.ui.button(label="✅ Akceptuj", style=nextcord.ButtonStyle.success, custom_id="urlop_edycja_accept_placeholder")
    async def accept_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Nie masz uprawnień.", ephemeral=True)
            return

        msg = interaction.message
        embed = msg.embeds[0] if msg.embeds else None
        if not embed:
            await interaction.response.send_message("❌ Nie mogę odczytać danych wniosku.", ephemeral=True)
            return

        # Odczytaj dane z embeda
        officer_name = ""
        new_end_date = ""
        applicant_id = None
        for field in embed.fields:
            if "Imię" in field.name:
                officer_name = field.value.strip()
            if "Nowa data" in field.name:
                new_end_date = field.value.strip()
        if embed.footer and embed.footer.text:
            try:
                applicant_id = int(embed.footer.text.split("ID:")[-1].strip())
            except Exception:
                pass

        # Zaktualizuj bazę
        record = await fetch_full_record()
        if not record:
            await interaction.response.send_message("❌ Błąd połączenia z bazą danych.", ephemeral=True)
            return

        officers = record.get("officers", [])
        officer = None
        for o in officers:
            if (o.get("name") or "").strip().lower() == officer_name.lower():
                officer = o
                break
        if not officer and applicant_id:
            member = interaction.guild.get_member(applicant_id)
            if member:
                for o in officers:
                    if (o.get("nick") or "").strip().lower() == member.name.lower():
                        officer = o
                        break

        if officer:
            officer["leaveEndDate"] = new_end_date
            ok = await save_full_record({"officers": officers})
            if not ok:
                await interaction.response.send_message("❌ Błąd zapisu do bazy danych.", ephemeral=True)
                return
            log.info(f"[URLOP] ✅ Edycja zaakceptowana: {officer_name} | nowa data: {new_end_date}")
        else:
            await interaction.response.send_message(
                f"⚠️ Nie znaleziono **{officer_name}** w bazie. Zaakceptowano, ale **status nie zmieniony** — zrób to ręcznie.",
                ephemeral=True
            )

        # Zaktualizuj embed
        new_embed = embed.copy()
        new_embed.color = 0x2ecc71
        new_embed.title = "✅ EDYCJA URLOPU ZAAKCEPTOWANA"
        new_embed.set_footer(text=f"{embed.footer.text if embed.footer else ''} • Zaakceptował: {interaction.user.name}")
        await msg.edit(embed=new_embed, view=None)
        if not officer:
            return
        await interaction.response.send_message("✅ Edycja urlopu zaakceptowana. Data zaktualizowana.", ephemeral=True)

        # Powiadom wnioskodawcę
        if applicant_id:
            member = interaction.guild.get_member(applicant_id)
            if member:
                try:
                    await member.send(
                        f"✅ Twój wniosek o edycję urlopu został **zaakceptowany** przez {interaction.user.mention}.\n"
                        f"Nowa data zakończenia urlopu: **{new_end_date}**"
                    )
                except Exception:
                    pass

    @nextcord.ui.button(label="❌ Odrzuć", style=nextcord.ButtonStyle.danger, custom_id="urlop_edycja_reject_placeholder")
    async def reject_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Nie masz uprawnień do odrzucania wniosków.", ephemeral=True)
            return
        await interaction.response.send_modal(UrlopEdycjaRejectModal(interaction.message))


# Modal odrzucenia edycji urlopu
class UrlopEdycjaRejectModal(nextcord.ui.Modal):
    def __init__(self, original_message: nextcord.Message):
        super().__init__(title="❌ Powód odrzucenia edycji urlopu", timeout=300)
        self.original_message = original_message

        self.reason = nextcord.ui.TextInput(
            label="Powód odrzucenia",
            placeholder="Podaj powód odrzucenia wniosku o edycję urlopu...",
            style=nextcord.TextInputStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        msg = self.original_message
        embed = msg.embeds[0] if msg.embeds else None
        applicant_id = None
        if embed and embed.footer and embed.footer.text:
            try:
                applicant_id = int(embed.footer.text.split("ID:")[-1].strip())
            except Exception:
                pass

        # Zaktualizuj embed
        new_embed = embed.copy() if embed else nextcord.Embed(title="❌ EDYCJA URLOPU ODRZUCONA")
        new_embed.color = 0xe74c3c
        new_embed.title = "❌ EDYCJA URLOPU ODRZUCONA"
        new_embed.add_field(name="💬 Powód odrzucenia", value=self.reason.value, inline=False)
        new_embed.set_footer(text=f"{embed.footer.text if embed and embed.footer else ''} • Odrzucił: {interaction.user.name}")
        await msg.edit(embed=new_embed, view=None)
        await interaction.response.send_message("❌ Wniosek o edycję urlopu odrzucony.", ephemeral=True)

        # Powiadom wnioskodawcę
        if applicant_id:
            member = interaction.guild.get_member(applicant_id)
            if member:
                try:
                    await member.send(
                        f"❌ Twój wniosek o edycję urlopu został **odrzucony** przez {interaction.user.mention}.\n"
                        f"**Powód:** {self.reason.value}"
                    )
                except Exception:
                    pass
        log.info(f"[URLOP] ❌ Edycja odrzucona przez {interaction.user.name} | powód: {self.reason.value}")

# Widok z przyciskami akceptacji/odrzucenia na kanale wniosków
class UrlopDecisionView(nextcord.ui.View):
    def __init__(self, officer_name: str = "", end_date_str: str = "", applicant_id: int = 0):
        super().__init__(timeout=None)
        self.officer_name  = officer_name
        self.end_date_str  = end_date_str
        self.applicant_id  = applicant_id

    def _encode_custom_id(self, action: str) -> str:
        # Kodujemy dane w custom_id żeby przeżyć restart bota
        # Format: urlop_{action}_{applicant_id}_{end_date_escaped}_{officer_name_escaped}
        safe_name = self.officer_name.replace("|", " ")
        safe_date = self.end_date_str.replace("|", "-")
        return f"urlop_{action}_{self.applicant_id}|{safe_date}|{safe_name}"

    @nextcord.ui.button(label="✅ Akceptuj", style=nextcord.ButtonStyle.success, custom_id="urlop_accept_placeholder")
    async def accept_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await _handle_urlop_decision(interaction, accepted=True)

    @nextcord.ui.button(label="❌ Odrzuć", style=nextcord.ButtonStyle.danger, custom_id="urlop_reject_placeholder")
    async def reject_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Nie masz uprawnień do odrzucania wniosków.", ephemeral=True)
            return
        await interaction.response.send_modal(UrlopRejectModal(interaction.message))

class UrlopRejectModal(nextcord.ui.Modal):
    def __init__(self, original_message: nextcord.Message):
        super().__init__(title="❌ Powód odrzucenia wniosku", timeout=300)
        self.original_message = original_message

        self.reason = nextcord.ui.TextInput(
            label="Powód odrzucenia",
            placeholder="Podaj powód odrzucenia wniosku urlopowego...",
            style=nextcord.TextInputStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        await _handle_urlop_decision(interaction, accepted=False, reason=self.reason.value.strip(), msg=self.original_message)

async def _handle_urlop_decision(interaction: nextcord.Interaction, accepted: bool, reason: str = "", msg: nextcord.Message = None):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Nie masz uprawnień do akceptowania wniosków.", ephemeral=True)
        return

    # Użyj przekazanej wiadomości lub pobierz z interaction
    if msg is None:
        msg = interaction.message
    embed = msg.embeds[0] if msg.embeds else None
    if not embed:
        await interaction.response.send_message("❌ Nie mogę odczytać danych wniosku.", ephemeral=True)
        return
    officer_name = ""
    end_date_str = ""
    start_date_str = ""
    applicant_id = None

    for field in embed.fields:
        if "Imię" in field.name:
            officer_name = field.value.strip()
        if "Zakończenie" in field.name:
            end_date_str = field.value.strip()
        if "Rozpoczęcie" in field.name:
            start_date_str = field.value.strip()

    # Pobierz applicant_id ze stopki
    if embed.footer and embed.footer.text:
        try:
            id_part = embed.footer.text.split("ID:")[-1].strip()
            applicant_id = int(id_part)
        except Exception:
            pass

    if not accepted:
        # Zaktualizuj embed z powodem odrzucenia
        new_embed = embed.copy()
        new_embed.color = 0xe74c3c
        new_embed.title = "❌ WNIOSEK ODRZUCONY"
        if reason:
            new_embed.add_field(name="💬 Powód odrzucenia", value=reason, inline=False)
        new_embed.set_footer(text=f"{embed.footer.text if embed.footer else ''} • Odrzucił: {interaction.user.name}")
        await msg.edit(embed=new_embed, view=None)
        await interaction.response.send_message("❌ Wniosek został odrzucony.", ephemeral=True)

        # Powiadom wnioskodawcę
        if applicant_id:
            member = interaction.guild.get_member(applicant_id)
            if member:
                try:
                    dm_text = f"❌ Twój wniosek o urlop został **odrzucony** przez {interaction.user.mention}."
                    if reason:
                        dm_text += f"\n\n**Powód:** {reason}"
                    await member.send(dm_text)
                except Exception:
                    pass
        log.info(f"[URLOP] ❌ Odrzucono wniosek: {officer_name} | {end_date_str} | przez {interaction.user.name} | powód: {reason or '—'}")
        return

    # Akceptacja — znajdź oficera w bazie i ustaw onLeave=True + leaveEndDate
    record = await fetch_full_record()
    if not record:
        await interaction.response.send_message("❌ Błąd połączenia z bazą danych.", ephemeral=True)
        return

    officers = record.get("officers", [])
    officer  = None
    for o in officers:
        if (o.get("name") or "").strip().lower() == officer_name.lower():
            officer = o
            break

    if not officer:
        # Spróbuj po nicku OOC jeśli nie znaleziono po imieniu
        if applicant_id:
            member = interaction.guild.get_member(applicant_id)
            if member:
                nick_lower = member.name.lower()
                for o in officers:
                    if (o.get("nick") or "").strip().lower() == nick_lower:
                        officer = o
                        break

    if not officer:
        await interaction.response.send_message(
            f"⚠️ Nie znaleziono funkcjonariusza **{officer_name}** w bazie.\nZaakceptowano wniosek, ale **nie zmieniono statusu w bazie** — zrób to ręcznie.",
            ephemeral=True
        )
    else:
        # Sprawdź czy data zakończenia nie jest już w przeszłości
        end_dt = _parse_date(end_date_str)
        now    = datetime.utcnow()
        if end_dt and now.date() > end_dt.date():
            await interaction.response.send_message(
                f"⚠️ Data zakończenia urlopu (**{end_date_str}**) już minęła — wniosek nieaktualny. Nie zmieniono statusu w bazie.",
                ephemeral=True
            )
            new_embed = embed.copy()
            new_embed.color = 0xe67e22
            new_embed.title = "⚠️ WNIOSEK NIEAKTUALNY (data minęła)"
            new_embed.set_footer(text=f"{embed.footer.text if embed.footer else ''} • Sprawdził: {interaction.user.name}")
            await msg.edit(embed=new_embed, view=None)
            # Powiadom wnioskodawcę na PW
            if applicant_id:
                member = interaction.guild.get_member(applicant_id)
                if member:
                    try:
                        await member.send(
                            f"⚠️ Twój wniosek o urlop został odrzucony przez {interaction.user.mention}, "
                            f"ponieważ podana data zakończenia (**{end_date_str}**) już minęła.\n"
                            f"Złóż wniosek ponownie z poprawną datą."
                        )
                    except Exception:
                        pass
            return
        officer["onLeave"]        = True
        officer["leaveEndDate"]   = end_date_str
        officer["leaveStartDate"] = start_date_str
        ok = await save_full_record({"officers": officers})
        if not ok:
            await interaction.response.send_message("❌ Błąd zapisu do bazy danych.", ephemeral=True)
            return
        log.info(f"[URLOP] ✅ Zaakceptowano: {officer_name} | urlop do {end_date_str}")

    # Zaktualizuj embed
    new_embed = embed.copy()
    new_embed.color = 0x2ecc71
    new_embed.title = "✅ WNIOSEK ZAAKCEPTOWANY"
    new_embed.set_footer(text=f"{embed.footer.text if embed.footer else ''} • Zaakceptował: {interaction.user.name}")
    await msg.edit(embed=new_embed, view=None)
    await interaction.response.send_message("✅ Wniosek zaakceptowany. Status funkcjonariusza zaktualizowany.", ephemeral=True)

    # Powiadom wnioskodawcę
    if applicant_id:
        member = interaction.guild.get_member(applicant_id)
        if member:
            try:
                await member.send(f"✅ Twój wniosek o urlop został **zaakceptowany** przez {interaction.user.mention}.\nUrlop trwa do: **{end_date_str}**")
            except Exception:
                pass

# ─── TASK: AUTOMATYCZNE KOŃCZENIE URLOPÓW ────────────────────────────────────
def _parse_date(date_str: str):
    """Parsuje datę w formacie d/m/Y, d.m.Y, d/m/yy, d.m.yy."""
    if not date_str:
        return None
    normalized = date_str.strip().replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%-d/%-m/%Y", "%-d/%-m/%y"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    return None

@tasks.loop(minutes=1)
async def leave_expiry_watch():
    """Co minutę sprawdza czy czyiś urlop się skończył i ustawia go z powrotem na aktywny."""
    await _run_leave_expiry()

async def _run_leave_expiry():
    """Właściwa logika sprawdzania wygasłych urlopów — wywoływana przez task i komendy."""
    record = await fetch_full_record()
    if not record:
        return
    officers  = record.get("officers", [])
    now       = datetime.utcnow().replace(tzinfo=None)
    changed   = []

    for o in officers:
        if not o.get("onLeave"):
            continue
        end_str = o.get("leaveEndDate", "").strip()
        if not end_str:
            continue
        end_dt = _parse_date(end_str)
        if not end_dt:
            log.warning(f"[URLOP] Nie można sparsować daty '{end_str}' dla {o.get('name')}")
            continue
        # Urlop kończy się po tym dniu (włącznie), więc zdejmujemy następnego dnia
        if now.date() > end_dt.date():
            o["onLeave"]        = False
            o["leaveEndDate"]   = ""
            o["leaveStartDate"] = ""
            changed.append(o.get("name", "?"))

    if changed:
        ok = await save_full_record({"officers": officers})
        if ok:
            log.info(f"[URLOP] Zakończono urlop dla: {', '.join(changed)}")
        else:
            log.error("[URLOP] Błąd zapisu po zakończeniu urlopów")

@leave_expiry_watch.before_loop
async def before_leave_expiry():
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
        all_roles   = all_rank_role_objects(interaction.guild, guild_roles)

        dept             = (officer.get("dept") or "LSPD").strip() or "LSPD"
        rank             = officer.get("rank", "")
        target_role, target_role_name = get_target_role(interaction.guild, dept, rank, guild_roles)
        target_role_name = target_role_name or "BRAK W MAPOWANIU"
        target_nick      = build_nickname(officer)

        current_lspd    = [r for r in member.roles if r in all_roles]
        has_target      = (target_role in member.roles) if target_role else False
        rank_to_remove  = [r for r in current_lspd if r != target_role]
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
            f"  dept: `{dept}`",
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

    @slash_command(name="rekrutacja-setup", description="Wysyła panel rekrutacyjny LSPD Vespucci", guild_ids=[GUILD_ID])
    async def cmd_rekrutacja_setup(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(RECRUITMENT_CHANNEL_ID) or interaction.channel

        embed = nextcord.Embed(
            title="🚔 Dołącz do LSPD Vespucci!",
            description=(
                "Hej! Jeśli szukasz miejsca, w którym liczy się profesjonalizm, "
                "dobra zabawa i luźne podejście do służby — **LSPD Vespucci** czeka właśnie na Ciebie!\n\n"
                "Masz chęć spróbować swoich sił w roli funkcjonariusza? "
                "Chcesz rozwijać swoją postać, brać udział w dynamicznych akcjach "
                "i tworzyć wspaniałe wspomnienia?\n\n"
                "Kliknij przycisk poniżej, aby otrzymać rolę i dołączyć do naszych szeregów!"
            ),
            color=0x1e5fc4,
            timestamp=datetime.utcnow()
        )
        embed.set_thumbnail(url=interaction.guild.me.display_avatar.url)
        embed.set_footer(text="Los Santos Police Department · Vespucci Division")

        await channel.send(embed=embed, view=JoinLSPDView())
        await interaction.response.send_message(f"✅ Panel rekrutacyjny wysłany na {channel.mention}.", ephemeral=True)

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

    @slash_command(name="urlop-test-expire", description="Wymuś natychmiastowe sprawdzenie wygasłych urlopów", guild_ids=[GUILD_ID])
    async def cmd_urlop_test_expire(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        # Pobierz stan PRZED
        record = await fetch_full_record()
        officers = record.get("officers", []) if record else []
        on_leave_before = [(o.get("name"), o.get("leaveEndDate")) for o in officers if o.get("onLeave")]

        # Odpal sprawdzenie
        await _run_leave_expiry()

        # Pobierz stan PO
        record2 = await fetch_full_record()
        officers2 = record2.get("officers", []) if record2 else []
        on_leave_after = [o.get("name") for o in officers2 if o.get("onLeave")]

        expired = [name for name, _ in on_leave_before if name not in on_leave_after]
        still_on = [(name, date) for name, date in on_leave_before if name in on_leave_after]

        lines = ["**🧪 Test wygaśnięcia urlopów**\n"]
        lines.append(f"**Przed:** {len(on_leave_before)} na urlopie")
        if on_leave_before:
            for name, date in on_leave_before:
                lines.append(f"  • {name} — do `{date}`")
        lines.append(f"\n**Po sprawdzeniu:**")
        if expired:
            lines.append(f"✅ Urlop wygasł i zdjęty: **{', '.join(expired)}**")
        if still_on:
            for name, date in still_on:
                lines.append(f"⏳ Nadal na urlopie: **{name}** (do `{date}`)")
        if not expired and not on_leave_before:
            lines.append("ℹ️ Nikt nie był na urlopie.")
        if not expired and on_leave_before:
            lines.append("ℹ️ Żaden urlop jeszcze nie wygasł (daty w przyszłości).")

        await interaction.followup.send("\n".join(lines), ephemeral=True)


    @slash_command(name="podanie-setup", description="Wysyła panel podań rekrutacyjnych LSPD", guild_ids=[GUILD_ID])
    async def cmd_podanie_setup(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(PODANIE_PANEL_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Nie znaleziono kanału podań.", ephemeral=True)
            return

        embed = nextcord.Embed(
            title="🚔 PODANIE DO LSPD VESPUCCI",
            description=(
                "Chcesz dołączyć do szeregów **Los Santos Police Department**?\n\n"
                "Wypełnij podanie klikając przycisk poniżej. Formularz składa się z **3 kroków** — "
                "odpowiedz na wszystkie pytania rzetelnie i zgodnie z prawdą.\n\n"
                "**Wymagania:**\n"
                "• Minimum **16 lat** [OOC]\n"
                "• Mutacja\n"
                "• Zaangażowanie i dobre chęci\n\n"
                "*Podanie zostanie rozpatrzone przez rekruterów LSPD.*"
            ),
            color=0x1e5fc4,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Los Santos Police Department · Vespucci Division")

        await channel.send(embed=embed, view=PodaniePanelView())
        await interaction.response.send_message(f"✅ Panel podań wysłany na {channel.mention}.", ephemeral=True)

    @slash_command(name="faq-setup", description="Wysyła FAQ na kanał informacyjny LSPD", guild_ids=[GUILD_ID])
    async def cmd_faq_setup(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        FAQ_CHANNEL_ID  = 1484390389103333606
        DATABASE_CH_ID  = 1474455483002654720

        channel = interaction.guild.get_channel(FAQ_CHANNEL_ID)
        if not channel:
            await interaction.followup.send(f"❌ Nie znaleziono kanału {FAQ_CHANNEL_ID}.", ephemeral=True)
            return

        db_ch      = interaction.guild.get_channel(DATABASE_CH_ID)
        db_mention = db_ch.mention if db_ch else f"<#{DATABASE_CH_ID}>"

        GOLD  = 0xc8a84b
        BLUE  = 0x1e5fc4
        RED   = 0xe03030
        GREEN = 0x2ecc71
        GRAY  = 0x2c3e50

        # ── Nagłówek ─────────────────────────────────────────────────────────
        header = nextcord.Embed(
            description=(
                "```\n"
                "  ██╗     ███████╗██████╗ ██████╗\n"
                "  ██║     ██╔════╝██╔══██╗██╔══██╗\n"
                "  ██║     ███████╗██████╔╝██║  ██║\n"
                "  ██║     ╚════██║██╔═══╝ ██║  ██║\n"
                "  ███████╗███████║██║     ██████╔╝\n"
                "  ╚══════╝╚══════╝╚═╝     ╚═════╝\n"
                "```\n"
                "**Los Santos Police Department — Vespucci Division**\n"
                "Poniżej znajdziesz wszystkie podstawowe informacje,\n"
                "które pomogą Ci sprawnie poruszać się w naszych szeregach."
            ),
            color=GOLD,
        )
        header.set_footer(text="LSPD Vespucci · Tablica Informacyjna")
        await channel.send(embed=header)

        # ── 1. Klawiszologia ─────────────────────────────────────────────────
        import pathlib
        img_path = pathlib.Path("/app/klawiszologia.png")
        if not img_path.exists():
            img_path = pathlib.Path("/home/claude/klawiszologia.png")

        embed_klaw = nextcord.Embed(
            title="🎮  1. Klawiszologia LSPD",
            description=(
                "Poniżej znajdziesz mapę klawiszy używanych podczas służby.\n"
                "**Kliknij obrazek**, aby go powiększyć."
            ),
            color=GOLD,
        )
        embed_klaw.set_image(url="attachment://klawiszologia.png")
        embed_klaw.set_footer(text="Tablica Operacyjna · LSPD Vespucci")

        if img_path.exists():
            with open(img_path, "rb") as f:
                await channel.send(embed=embed_klaw, file=nextcord.File(f, filename="klawiszologia.png"))
        else:
            await channel.send(embed=embed_klaw)

        # ── 2. Komendy ───────────────────────────────────────────────────────
        embed_cmd = nextcord.Embed(
            title="⌨️  2. Podstawowe komendy",
            color=BLUE,
        )
        embed_cmd.add_field(
            name="╔══ KOMENDY SŁUŻBOWE ══╗",
            value=(
                "> `/odznaka` — wyświetla Twoją odznakę służbową\n"
                "> `/lspd [treść]` — ogłoszenie dla obywateli *(Police Announce)*\n"
                "> `/10-13` — wysyła powiadomienie o byciu **rannym** do pozostałych jednostek i EMS\n"
                "> `/panic` — wysyła alarm **CODE 0** do wszystkich jednostek\n"
            ),
            inline=False,
        )
        embed_cmd.set_footer(text="Używaj komend odpowiedzialnie · LSPD Vespucci")
        await channel.send(embed=embed_cmd)

        # ── 3. Database & Kompendium ─────────────────────────────────────────
        embed_db = nextcord.Embed(
            title="🗄️  3. Database & Kompendium",
            description=f"Wszystkie zasoby znajdziesz w {db_mention}",
            color=BLUE,
        )
        embed_db.add_field(
            name="📊 Database zawiera m.in.",
            value=(
                "• Szkoleniowców FTD i commanderów wydziałów oraz ich zasady rekrutacji\n"
                "• Cały spis funkcjonariuszy\n"
                "• Możliwość napisania raportu w dzienniku\n"
                "• Prowadzących kadetów\n"
                "• Wypłaty i kalendarz urlopów"
            ),
            inline=True,
        )
        embed_db.add_field(
            name="📖 Kompendium zawiera m.in.",
            value=(
                "• Wszystkie potrzebne informacje i procedury\n"
                "• Zdjęcia i nagrania szkoleniowe\n"
                "• Wymagane szkolenia na dany stopień\n"
                "• Osobne kompendium dla każdego wydziału"
            ),
            inline=True,
        )
        embed_db.set_footer(text="LSPD Vespucci · Zasoby służbowe")
        await channel.send(embed=embed_db)

        # ── 4. Awanse ────────────────────────────────────────────────────────
        embed_awans = nextcord.Embed(
            title="⭐  4. Na jakiej podstawie wystawiane są awanse?",
            color=GREEN,
            description="Awanse wystawiane są przez **High Command** na podstawie:\n",
        )
        embed_awans.add_field(
            name="\u200b",
            value=(
                "✦ Zaangażowania i wyróżniania się na służbie\n"
                "✦ Wypisanych raportów i godzin w dzienniku\n"
                "✦ Wyrobionych szkoleń w wydziale\n"
                "✦ Wypełniania obowiązków wydziałowych"
            ),
            inline=False,
        )
        embed_awans.set_footer(text="Staraj się, a awans przyjdzie sam · LSPD Vespucci")
        await channel.send(embed=embed_awans)

        # ── 5. Kadet ─────────────────────────────────────────────────────────
        embed_kadet = nextcord.Embed(
            title="🎓  5. Co musi wiedzieć Kadet?",
            color=RED,
        )
        embed_kadet.add_field(
            name="╔══ ZASADY OBOWIĄZKOWE ══╗",
            value=(
                "🚫 **Zakaz** samodzielnego wyjazdu w patrol\n"
                "🚫 **Zakaz** posiadania broni palnej bez licencji *(licencje wyrabiamy od Oficera I+)*\n"
                "📅 Tydzień od momentu przyjęcia na zdanie egzaminu oficerskiego — można podejść maksymalnie **2 razy**\n"
                "👤 Swojego prowadzącego znajdziesz w **Database**\n"
                "🚫 W trakcie akcji agresywnych **zakaz wysiadania z radiowozu** *(nie wliczasz się do limitu na akcję)*"
            ),
            inline=False,
        )
        embed_kadet.set_footer(text="Krok po kroku do odznaki · LSPD Vespucci")
        await channel.send(embed=embed_kadet)

        # ── 6. Norma & Urlop ─────────────────────────────────────────────────
        embed_norma = nextcord.Embed(
            title="⏱️  6. Norma godzinowa & Urlopy",
            color=GRAY,
            description=(
                "U nas **nie ma normy godzinowej** — wymagamy jedynie aktywności na Discordzie, "
                "tzn. zostawiania reakcji na wiadomości.\n\n"
                "Przy dłuższej nieobecności **zalecamy wypisanie urlopu**, aby uniknąć degradacji."
            ),
        )
        embed_norma.set_footer(text="Dbamy o Twój czas · LSPD Vespucci")
        await channel.send(embed=embed_norma)

        # ── 7. Zakaz broni ───────────────────────────────────────────────────
        embed_bron = nextcord.Embed(
            title="🔫  7. Zakaz broni",
            color=GRAY,
            description="🚫 Zakaz korzystania z broni innej niż ta, która znajduje się w **szafce policyjnej**.",
        )
        embed_bron.set_footer(text="Dbaj o sprzęt służbowy · LSPD Vespucci")
        await channel.send(embed=embed_bron)

        # ── 8. Kamizelki ─────────────────────────────────────────────────────
        embed_kamiz = nextcord.Embed(
            title="🛡️  8. Kamizelki kuloodporne",
            color=GRAY,
            description="✅ Można pobierać **kamizelki kuloodporne** na napady.",
        )
        embed_kamiz.set_footer(text="Bezpieczeństwo przede wszystkim · LSPD Vespucci")
        await channel.send(embed=embed_kamiz)

        # ── 9. Skargi ────────────────────────────────────────────────────────
        embed_skargi = nextcord.Embed(
            title="⚖️  9. Skargi na funkcjonariuszy",
            color=RED,
            description=(
                "Wszelkie skargi na funkcjonariuszy składamy do **IAD** *(Internal Affairs Division)*.\n\n"
                "Rozmowa z **High Command** jest absolutną ostatecznością!"
            ),
        )
        embed_skargi.set_footer(text="IAD — wewnętrzny nadzór · LSPD Vespucci")
        await channel.send(embed=embed_skargi)

        # ── 10. Zaproszenie znajomego ─────────────────────────────────────────
        embed_znajomy = nextcord.Embed(
            title="🤝  10. Chcesz zaprosić znajomego?",
            color=GREEN,
            description=(
                "Jesteśmy **w pełni otwarci** na takie propozycje! 🎉\n\n"
                "Osoba polecona przez Ciebie może dołączyć **bez pisania podania** — "
                "wystarczy skontaktować się z **High Command** i przedstawić kandydata."
            ),
        )
        embed_znajomy.set_footer(text="Razem tworzymy LSPD · Vespucci Division")
        await channel.send(embed=embed_znajomy)

        # ── Stopka ───────────────────────────────────────────────────────────
        footer_embed = nextcord.Embed(
            description=(
                "```\n"
                "  Los Santos Police Department · Vespucci Division\n"
                "  Protect and Serve\n"
                "```"
            ),
            color=GOLD,
        )
        await channel.send(embed=footer_embed)
        await interaction.followup.send(f"✅ FAQ zostało wysłane na {channel.mention}!", ephemeral=True)
        log.info(f"[FAQ] Wysłano FAQ przez {interaction.user.name}")
    async def cmd_urlop_setup(self, interaction: Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj serwerem**.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(URLOP_PANEL_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Nie znaleziono kanału urlopowego.", ephemeral=True)
            return

        embed = nextcord.Embed(
            title="🏖️ SYSTEM URLOPOWY — LSPD",
            description=(
                "Planujesz przerwę od służby?\n\n"
                "Kliknij przycisk poniżej, wypełnij formularz i poczekaj na akceptację przełożonych.\n\n"
                "**Pamiętaj:**\n"
                "• Urlop wymaga akceptacji High Command\n"
                "• Podaj dokładne daty rozpoczęcia i zakończenia\n"
                "• Status zostanie automatycznie zmieniony po akceptacji\n"
                "• Po zakończeniu okresu urlop wygasa automatycznie"
            ),
            color=0x3498db,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Los Santos Police Department · System Urlopowy")

        await channel.send(embed=embed, view=UrlopPanelView())
        await interaction.response.send_message(f"✅ Panel urlopowy wysłany na {channel.mention}.", ephemeral=True)


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

# ─── SYSTEM PODAŃ LSPD ───────────────────────────────────────────────────────
PODANIE_PANEL_CHANNEL_ID  = 1473729901495582741   # kanał z guzikiem
PODANIE_WYNIKI_CHANNEL_ID = 1368235633197187154   # kanał z wynikami do akceptacji
PODANIE_ROLA_ID           = 1480320527691153681   # rola nadawana po akceptacji

class PodanieModal(nextcord.ui.Modal):
    def __init__(self):
        super().__init__(title="📋 Podanie do LSPD Vespucci", timeout=600)

        self.wiek = nextcord.ui.TextInput(
            label="Wiek [OOC]",
            placeholder="np. 20",
            required=True, max_length=10,
        )
        self.mutacje = nextcord.ui.TextInput(
            label="Mutacje? [OOC]",
            placeholder="Tak / Nie — jeśli tak, jakie?",
            required=True, max_length=150,
        )
        self.doswiadczenie = nextcord.ui.TextInput(
            label="Doświadczenie jako policjant [IC]",
            placeholder="Opisz swoje doświadczenie w formie IC...",
            style=nextcord.TextInputStyle.paragraph,
            required=True, max_length=1000,
        )
        self.dlaczego = nextcord.ui.TextInput(
            label="Dlaczego powinieneś być przyjęty? [IC]",
            placeholder="Przekonaj nas w formie IC...",
            style=nextcord.TextInputStyle.paragraph,
            required=True, max_length=2000,
        )
        self.rp_exp = nextcord.ui.TextInput(
            label="Doświadczenie RP [OOC]",
            placeholder="Na jakich serwerach grałeś? Jakie masz doświadczenie w RP?",
            style=nextcord.TextInputStyle.paragraph,
            required=True, max_length=1000,
        )
        self.add_item(self.wiek)
        self.add_item(self.mutacje)
        self.add_item(self.doswiadczenie)
        self.add_item(self.dlaczego)
        self.add_item(self.rp_exp)

    async def callback(self, interaction: nextcord.Interaction):
        channel = interaction.guild.get_channel(PODANIE_WYNIKI_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Błąd — kanał wyników nie znaleziony.", ephemeral=True)
            return

        embed = nextcord.Embed(
            title="📋 NOWE PODANIE DO LSPD VESPUCCI",
            color=0x1e5fc4,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="🎂 Wiek [OOC]",                       value=self.wiek.value,          inline=True)
        embed.add_field(name="🧬 Czy posiadasz mutacje?",            value=self.mutacje.value,       inline=True)
        embed.add_field(name="🏛️ Doświadczenie jako funkcjonariusz [IC]",
                        value=self.doswiadczenie.value, inline=False)
        embed.add_field(name="💬 Dlaczego powinieneś zostać przyjęty? [IC]",
                        value=self.dlaczego.value,     inline=False)
        embed.add_field(name="🎮 Doświadczenie w RP [OOC]",
                        value=self.rp_exp.value,       inline=False)
        embed.set_footer(text=f"Składający: {interaction.user.name} • ID: {interaction.user.id}")

        await channel.send(content=interaction.user.mention, embed=embed, view=PodanieDecisionView())
        await interaction.response.send_message(
            "✅ Twoje podanie zostało wysłane! Poczekaj na decyzję rekruterów.",
            ephemeral=True
        )
        log.info(f"[PODANIE] Złożone przez {interaction.user.name} ({interaction.user.id})")


class PodaniePanelView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(
        label="📋  Wyślij podanie",
        style=nextcord.ButtonStyle.primary,
        custom_id="podanie_wyslij_btn"
    )
    async def podanie_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(PodanieModal())


class PodanieDecisionView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="✅ Akceptuj", style=nextcord.ButtonStyle.success, custom_id="podanie_accept_btn")
    async def accept_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Nie masz uprawnień.", ephemeral=True)
            return
        await _handle_podanie_decision(interaction, accepted=True)

    @nextcord.ui.button(label="❌ Odrzuć", style=nextcord.ButtonStyle.danger, custom_id="podanie_reject_btn")
    async def reject_btn(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Nie masz uprawnień.", ephemeral=True)
            return
        await interaction.response.send_modal(PodanieRejectModal(interaction.message))


class PodanieRejectModal(nextcord.ui.Modal):
    def __init__(self, original_message: nextcord.Message):
        super().__init__(title="❌ Powód odrzucenia podania", timeout=300)
        self.original_message = original_message

        self.reason = nextcord.ui.TextInput(
            label="Powód odrzucenia",
            placeholder="Podaj powód odrzucenia podania...",
            style=nextcord.TextInputStyle.paragraph,
            required=True, max_length=500,
        )
        self.add_item(self.reason)

    async def callback(self, interaction: nextcord.Interaction):
        await _handle_podanie_decision(
            interaction, accepted=False,
            reason=self.reason.value.strip(),
            msg=self.original_message
        )


async def _handle_podanie_decision(
    interaction: nextcord.Interaction,
    accepted: bool,
    reason: str = "",
    msg: nextcord.Message = None
):
    if msg is None:
        msg = interaction.message
    embed = msg.embeds[0] if msg.embeds else None
    if not embed:
        await interaction.response.send_message("❌ Nie mogę odczytać danych podania.", ephemeral=True)
        return

    applicant_id = None
    if embed.footer and embed.footer.text:
        try:
            applicant_id = int(embed.footer.text.split("ID:")[-1].strip())
        except Exception:
            pass

    member = interaction.guild.get_member(applicant_id) if applicant_id else None

    if not accepted:
        new_embed = embed.copy()
        new_embed.color = 0xe74c3c
        new_embed.title = "❌ PODANIE ODRZUCONE"
        if reason:
            new_embed.add_field(name="💬 Powód odrzucenia", value=reason, inline=False)
        new_embed.set_footer(text=f"{embed.footer.text if embed.footer else ''} • Odrzucił: {interaction.user.name}")
        await msg.edit(embed=new_embed, view=None)
        await interaction.response.send_message("❌ Podanie odrzucone.", ephemeral=True)
        if member:
            try:
                dm = "Twoje podanie do LSPD Vespucci zostało odrzucone"
                if reason:
                    dm += f" z powodu: {reason}"
                await member.send(dm)
            except Exception:
                pass
        log.info(f"[PODANIE] ❌ Odrzucono ID={applicant_id} | przez {interaction.user.name} | powód: {reason or '—'}")
        return

    role = interaction.guild.get_role(PODANIE_ROLA_ID)
    if role and member:
        try:
            await member.add_roles(role, reason=f"Podanie przyjęte przez {interaction.user.name}")
        except nextcord.Forbidden:
            log.error(f"[PODANIE] Brak uprawnień do nadania roli {PODANIE_ROLA_ID}")
    elif not role:
        log.error(f"[PODANIE] Nie znaleziono roli {PODANIE_ROLA_ID}")

    new_embed = embed.copy()
    new_embed.color = 0x2ecc71
    new_embed.title = "✅ PODANIE PRZYJĘTE"
    new_embed.set_footer(text=f"{embed.footer.text if embed.footer else ''} • Zaakceptował: {interaction.user.name}")
    await msg.edit(embed=new_embed, view=None)
    await interaction.response.send_message("✅ Podanie przyjęte. Rola nadana.", ephemeral=True)
    if member:
        try:
            await member.send(
                "Twoje podanie do LSPD Vespucci zostało przyjęte, na kanale akademia znajdziesz datę "
                "następnej akademii, oraz wszystkie informacje. Gratulacje i do zobaczenia!"
            )
        except Exception:
            pass
    log.info(f"[PODANIE] ✅ Przyjęto ID={applicant_id} ({member.name if member else '?'}) | przez {interaction.user.name}")


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

# ─── PRZYCISK DOŁĄCZ DO LSPD ─────────────────────────────────────────────────
RECRUITMENT_ROLE_ID     = 1473730397425897695
RECRUITMENT_CHANNEL_ID  = 1473733264148660319

class JoinLSPDView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(
        label="📋 Dołącz do LSPD Vespucci!",
        style=nextcord.ButtonStyle.primary,
        custom_id="join_lspd_button"
    )
    async def join_button(self, button: nextcord.ui.Button, interaction: Interaction):
        guild = interaction.guild
        role  = guild.get_role(RECRUITMENT_ROLE_ID)

        if not role:
            await interaction.response.send_message(
                "❌ Nie znaleziono roli rekrutacyjnej. Skontaktuj się z administracją.",
                ephemeral=True
            )
            log.error(f"[JOIN] Nie znaleziono roli o ID {RECRUITMENT_ROLE_ID}!")
            return

        if role in interaction.user.roles:
            await interaction.response.send_message(
                "ℹ️ Masz już tę rolę! Sprawdź kanały LSPD Vespucci.",
                ephemeral=True
            )
            return

        try:
            await interaction.user.add_roles(role, reason="Przycisk: Dołącz do LSPD Vespucci")
            await interaction.response.send_message(
                f"✅ Witaj w szeregach **LSPD Vespucci**, {interaction.user.mention}!\n"
                f"Nadano Ci rolę **{role.name}**. Powodzenia w służbie! 🚔",
                ephemeral=True
            )
            log.info(f"[JOIN] {interaction.user} otrzymał rolę {role.name}")
        except nextcord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot nie ma uprawnień do nadania roli. Skontaktuj się z administracją.",
                ephemeral=True
            )
            log.error(f"[JOIN] Brak uprawnień do nadania roli {role.name} dla {interaction.user}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Błąd: {e}", ephemeral=True)
            log.error(f"[JOIN] Błąd: {e}")


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

# ─── SZKOLENIA FTD ────────────────────────────────────────────────────────────
SZKOLENIA_CHANNEL_ID = 1477376597974581480

# Lista szkoleń i odpowiadające im klucze w bazie oficerów
FTD_TRAININGS = [
    ("SEU", "seu"),
    ("SV",  "sv"),
    ("NT",  "nt"),
    ("PWC", "pwc"),
    ("WU",  "wu"),
    ("K9",  "k9"),
    ("ASU", "asu"),
]

class SzkoleniaSelectView(nextcord.ui.View):
    """Stała wiadomość z menu wyboru szkolenia — persist po restarcie."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SzkoleniSelect())

class SzkoleniSelect(nextcord.ui.Select):
    def __init__(self):
        options = [
            nextcord.SelectOption(label=name, value=key, emoji="🎓")
            for name, key in FTD_TRAININGS
        ]
        super().__init__(
            placeholder="📋 Wybierz szkolenie...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="szkolenia_select_menu",
        )

    async def callback(self, interaction: nextcord.Interaction):
        training_key  = self.values[0]
        training_name = next((n for n, k in FTD_TRAININGS if k == training_key), training_key.upper())
        modal = SzkoleniaFormModal(training_name, training_key)
        await interaction.response.send_modal(modal)


class SzkoleniaFormModal(nextcord.ui.Modal):
    def __init__(self, training_name: str, training_key: str):
        super().__init__(title=f"Szkolenie: {training_name}", timeout=300)
        self.training_name = training_name
        self.training_key  = training_key

        self.zdajacy = nextcord.ui.TextInput(
            label="Imię i nazwisko zdającego",
            placeholder="np. Jan Kowalski",
            required=True,
            max_length=80,
            custom_id="szkolenie_zdajacy",
        )
        self.szkoleniowiec = nextcord.ui.TextInput(
            label="Imię i nazwisko szkoleniowca",
            placeholder="np. Anna Nowak",
            required=True,
            max_length=80,
            custom_id="szkolenie_szkoleniowiec",
        )
        self.add_item(self.zdajacy)
        self.add_item(self.szkoleniowiec)

    async def callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)

        zdajacy_name       = self.zdajacy.value.strip()
        szkoleniowiec_name = self.szkoleniowiec.value.strip()
        guild              = interaction.guild

        officers = await fetch_officers()
        nick_to_member    = {m.name.lower(): m for m in guild.members if not m.bot}
        display_to_member = {m.display_name.lower(): m for m in guild.members if not m.bot}

        # ── Szukaj zdającego w bazie (żeby go potem powiadomić) ──────────────
        zdajacy_officer = next(
            (o for o in officers
             if (o.get("name") or "").strip().lower() == zdajacy_name.lower()),
            None
        )
        zdajacy_member = None
        if zdajacy_officer:
            nick = (zdajacy_officer.get("nick") or "").strip().lower()
            zdajacy_member = nick_to_member.get(nick) or display_to_member.get(nick)

        # ── Szukaj szkoleniowca w bazie ────────────────────────────────────────
        trainer_officer = next(
            (o for o in officers
             if (o.get("name") or "").strip().lower() == szkoleniowiec_name.lower()),
            None
        )
        trainer_member = None
        if trainer_officer:
            nick = (trainer_officer.get("nick") or "").strip().lower()
            trainer_member = nick_to_member.get(nick) or display_to_member.get(nick)

        if not trainer_member:
            trainer_member = display_to_member.get(szkoleniowiec_name.lower())

        # ── Błąd: nie znaleziono szkoleniowca — pokaż podobne nazwiska ────────
        if not trainer_officer and not trainer_member:
            # Znajdź podobnych oficerów (pierwsze słowo nazwiska pasuje)
            query_parts = szkoleniowiec_name.lower().split()
            similar = [
                o.get("name") for o in officers
                if o.get("name") and any(
                    part in (o.get("name") or "").lower()
                    for part in query_parts
                )
            ][:5]

            hint = ""
            if similar:
                hint = "\n\n🔍 **Może chodziło Ci o:**\n" + "\n".join(f"• {n}" for n in similar)

            await interaction.followup.send(
                f"❌ **Nie znaleziono szkoleniowca o nazwie '{szkoleniowiec_name}' w bazie danych.**\n"
                f"Sprawdź czy wpisałeś poprawne imię i nazwisko (tak jak widnieje w bazie).{hint}",
                ephemeral=True
            )
            return

        if not trainer_member:
            await interaction.followup.send(
                f"❌ Znaleziono **{szkoleniowiec_name}** w bazie, ale nie można go znaleźć na Discordzie.\n"
                f"Upewnij się, że jest na serwerze i ma ustawiony prawidłowy nick.",
                ephemeral=True
            )
            return

        # ── Wyślij DM do szkoleniowca ─────────────────────────────────────────
        try:
            view = SzkoleniaDecisionView(
                zdajacy_name=zdajacy_name,
                szkoleniowiec_name=szkoleniowiec_name,
                training_name=self.training_name,
                training_key=self.training_key,
                zdajacy_member_id=zdajacy_member.id if zdajacy_member else None,
            )
            embed = nextcord.Embed(
                title="🎓 Potwierdzenie szkolenia",
                description=(
                    f"Siemka, tu Jarvis. Upewniam się czy pan **{zdajacy_name}** zdał szkolenie **{self.training_name}**?"
                ),
                color=0x1e5fc4,
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="LSPD FTD — System Szkoleń")
            await trainer_member.send(embed=embed, view=view)
            await interaction.followup.send(
                f"✅ Wysłano zapytanie do szkoleniowca **{szkoleniowiec_name}**.\n"
                f"Czekaj na jego odpowiedź — dostaniesz wiadomość z wynikiem.",
                ephemeral=True
            )
            log.info(f"[SZKOLENIA] Zapytanie do {szkoleniowiec_name} o szkolenie {self.training_name} dla {zdajacy_name}")
        except nextcord.Forbidden:
            await interaction.followup.send(
                f"❌ Nie mogę wysłać DM do **{szkoleniowiec_name}** — ma wyłączone wiadomości prywatne.",
                ephemeral=True
            )
        except Exception as e:
            log.error(f"[SZKOLENIA] Błąd DM: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Błąd: {e}", ephemeral=True)


class SzkoleniaDecisionView(nextcord.ui.View):
    """Przyciski Tak/Nie wysyłane do szkoleniowca w DM."""
    def __init__(self, zdajacy_name: str, szkoleniowiec_name: str,
                 training_name: str, training_key: str, zdajacy_member_id: int | None = None):
        super().__init__(timeout=86400)  # 24h timeout
        self.zdajacy_name       = zdajacy_name
        self.szkoleniowiec_name = szkoleniowiec_name
        self.training_name      = training_name
        self.training_key       = training_key
        self.zdajacy_member_id  = zdajacy_member_id

    async def _disable_all(self, message):
        for item in self.children:
            item.disabled = True
        try:
            await message.edit(view=self)
        except Exception:
            pass

    async def _notify_zdajacy(self, result: bool):
        """Wyślij DM do zdającego z wynikiem szkolenia."""
        if not self.zdajacy_member_id:
            return
        try:
            zdajacy_member = bot.get_user(self.zdajacy_member_id)
            if not zdajacy_member:
                zdajacy_member = await bot.fetch_user(self.zdajacy_member_id)
            if result:
                embed = nextcord.Embed(
                    title="✅ Szkolenie zaliczone!",
                    description=(
                        f"Gratulacje! Szkoleniowiec **{self.szkoleniowiec_name}** potwierdził, "
                        f"że zdałeś szkolenie **{self.training_name}**.\n\n"
                        f"Szkolenie zostało zapisane w Twojej teczce. 🎓"
                    ),
                    color=0x2ecc71,
                    timestamp=datetime.utcnow()
                )
            else:
                embed = nextcord.Embed(
                    title="❌ Szkolenie niezaliczone",
                    description=(
                        f"Szkoleniowiec **{self.szkoleniowiec_name}** poinformował, "
                        f"że nie zdałeś szkolenia **{self.training_name}**.\n\n"
                        f"W razie wątpliwości skontaktuj się bezpośrednio ze szkoleniowcem."
                    ),
                    color=0xe74c3c,
                    timestamp=datetime.utcnow()
                )
            embed.set_footer(text="LSPD FTD — System Szkoleń")
            await zdajacy_member.send(embed=embed)
        except Exception as e:
            log.warning(f"[SZKOLENIA] Nie udało się powiadomić zdającego ({self.zdajacy_member_id}): {e}")

    @nextcord.ui.button(label="✅ Tak", style=nextcord.ButtonStyle.success, custom_id="szkolenie_tak")
    async def btn_tak(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        await self._disable_all(interaction.message)

        # Znajdź oficera w bazie i zaktualizuj szkolenie
        officers = await fetch_officers()
        officer = next(
            (o for o in officers
             if (o.get("name") or "").strip().lower() == self.zdajacy_name.lower()),
            None
        )
        if not officer:
            await interaction.followup.send(
                f"❌ Nie znaleziono oficera **{self.zdajacy_name}** w bazie danych!\n"
                f"Skontaktuj się z administratorem — wpis może być konieczny ręcznie.",
            )
            return

        success = await update_officer(officer["id"], {
            self.training_key: True,
            f"{self.training_key}_fto": self.szkoleniowiec_name,
            f"{self.training_key}_date": datetime.utcnow().strftime("%Y-%m-%d"),
        })
        if success:
            await interaction.followup.send(
                f"✅ Zatwierdzone! **{self.zdajacy_name}** został oznaczony jako posiadający szkolenie **{self.training_name}** w bazie.",
            )
            await self._notify_zdajacy(result=True)
            log.info(f"[SZKOLENIA] {self.zdajacy_name} zaliczył {self.training_name} — potwierdził {self.szkoleniowiec_name}")
        else:
            await interaction.followup.send(
                f"❌ Błąd zapisu do bazy danych. Spróbuj ponownie lub zaktualizuj ręcznie.",
            )

    @nextcord.ui.button(label="❌ Nie", style=nextcord.ButtonStyle.danger, custom_id="szkolenie_nie")
    async def btn_nie(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        await self._disable_all(interaction.message)
        await interaction.followup.send(
            f"❌ Odrzucono. **{self.zdajacy_name}** nie zaliczył szkolenia **{self.training_name}**.",
        )
        await self._notify_zdajacy(result=False)
        log.info(f"[SZKOLENIA] {self.zdajacy_name} NIE zaliczył {self.training_name} — potwierdził {self.szkoleniowiec_name}")


# Komenda slash do wysłania panelu szkoleń na kanał
@bot.slash_command(guild_ids=[GUILD_ID], name="szkolen_panel", description="Wyślij panel szkoleń FTD na kanał")
async def szkolen_panel(interaction: nextcord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Brak uprawnień.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(SZKOLENIA_CHANNEL_ID)
    if not channel:
        await interaction.response.send_message(f"❌ Kanał {SZKOLENIA_CHANNEL_ID} nie znaleziony.", ephemeral=True)
        return

    embed = nextcord.Embed(
        title="🎓 System Szkoleń FTD",
        description=(
            "Wybierz szkolenie z listy poniżej, aby zarejestrować jego zaliczenie.\n\n"
            "**Dostępne szkolenia:**\n"
            + "\n".join(f"• **{name}**" for name, _ in FTD_TRAININGS) +
            "\n\nPo wybraniu szkolenia wypełnij formularz z imieniem i nazwiskiem zdającego oraz szkoleniowca."
        ),
        color=0x1e5fc4,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="LSPD FTD — System Szkoleń")

    view = SzkoleniaSelectView()
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"✅ Panel wysłany na {channel.mention}", ephemeral=True)


# ─── ON READY ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"✅ Bot online: {bot.user} | Serwer: {GUILD_ID} | Sync co {SYNC_INTERVAL_MIN} min")
    bot.add_view(TicketSelectView())
    bot.add_view(CloseTicketView())
    bot.add_view(JoinLSPDView())
    bot.add_view(UrlopPanelView())
    bot.add_view(UrlopDecisionView())
    bot.add_view(UrlopEdycjaDecisionView())
    bot.add_view(PodaniePanelView())
    bot.add_view(PodanieDecisionView())
    bot.add_view(SzkoleniaSelectView())
    if not auto_sync.is_running():
        auto_sync.start()
    if not iad_akta_watch.is_running():
        iad_akta_watch.start()
    if not announce_watch.is_running():
        announce_watch.start()
    if not leave_expiry_watch.is_running():
        leave_expiry_watch.start()
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
