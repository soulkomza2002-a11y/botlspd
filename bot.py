import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import os
import logging
from datetime import datetime

# ─── KONFIGURACJA ─────────────────────────────────────────────────────────────
DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN")
GUILD_ID          = int(os.getenv("GUILD_ID", "0"))
JSONBIN_BIN_ID    = os.getenv("JSONBIN_BIN_ID",  "6998859343b1c97be98eb84c")
JSONBIN_API_KEY   = os.getenv("JSONBIN_API_KEY",  "$2a$10$3L8S1mGNReuQXCj1pvYGaeUH0o1HosE59kmJC6exDhU.1aVPMY0fy")
SYNC_INTERVAL_MIN = int(os.getenv("SYNC_INTERVAL", "5"))
LOG_CHANNEL_ID    = int(os.getenv("LOG_CHANNEL_ID", "0"))  # opcjonalnie

# ─── MAPOWANIE STOPIEŃ → NAZWA ROLI NA DISCORDZIE ─────────────────────────────
# Zmień nazwy ról żeby pasowały do twoich ról na serwerze Discord
RANK_TO_ROLE = {
    "Chief of Police":  "Chief of Police",
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
}

# Wszystkie możliwe role LSPD (bot będzie nimi zarządzał)
ALL_LSPD_ROLES = set(RANK_TO_ROLE.values())

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("lspd-bot")

# ─── BOT SETUP ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── POBIERANIE DANYCH Z JSONBIN ──────────────────────────────────────────────
async def fetch_officers() -> list[dict]:
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest"
    headers = {"X-Master-Key": JSONBIN_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                log.error(f"JSONBin fetch failed: HTTP {resp.status}")
                return []
            data = await resp.json()
            return data.get("record", {}).get("officers", [])

# ─── GŁÓWNA LOGIKA SYNC ───────────────────────────────────────────────────────
async def sync_roles(guild: discord.Guild) -> dict:
    officers = await fetch_officers()
    if not officers:
        return {"error": "Nie udało się pobrać danych z bazy"}

    # Zbuduj mapę: nick_lowercase → stopień
    nick_map: dict[str, str] = {}
    for o in officers:
        nick = (o.get("nick") or "").strip().lower()
        rank = o.get("rank", "")
        if nick and rank in RANK_TO_ROLE:
            nick_map[nick] = rank

    results = {"updated": [], "skipped": [], "not_found": [], "errors": []}

    # Pobierz wszystkie role z serwera
    guild_roles: dict[str, discord.Role] = {r.name: r for r in guild.roles}

    for member in guild.members:
        if member.bot:
            continue

        # Dopasuj: najpierw po server nicku (display_name), potem username
        # nick_map ma nick OOC z bazy jako klucz
        display_lower  = member.display_name.lower()   # nick na serwerze (lub username jeśli brak)
        username_lower = member.name.lower()            # username konta Discord

        matched_rank = nick_map.get(display_lower) or nick_map.get(username_lower)

        if not matched_rank:
            results["not_found"].append(member.display_name)
            continue

        target_role_name = RANK_TO_ROLE[matched_rank]
        target_role = guild_roles.get(target_role_name)

        if not target_role:
            results["errors"].append(f"Brak roli '{target_role_name}' na serwerze")
            continue

        # Sprawdź czy już ma właściwą rolę
        current_lspd_roles = [r for r in member.roles if r.name in ALL_LSPD_ROLES]
        has_target = any(r.name == target_role_name for r in member.roles)

        if has_target and len(current_lspd_roles) == 1:
            results["skipped"].append(member.display_name)
            continue

        try:
            # Usuń stare role LSPD
            roles_to_remove = [r for r in member.roles if r.name in ALL_LSPD_ROLES and r.name != target_role_name]
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="LSPD Bot sync")

            # Dodaj nową rolę jeśli jej nie ma
            if not has_target:
                await member.add_roles(target_role, reason="LSPD Bot sync")

            results["updated"].append(f"{member.display_name} → {target_role_name}")
            log.info(f"Updated {member.display_name}: {[r.name for r in roles_to_remove]} → {target_role_name}")

        except discord.Forbidden:
            results["errors"].append(f"Brak uprawnień do edycji ról: {member.display_name}")
        except Exception as e:
            results["errors"].append(f"{member.display_name}: {e}")

    return results

# ─── FORMAT RAPORTU ───────────────────────────────────────────────────────────
def format_report(results: dict, duration: float) -> list[discord.Embed]:
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    embeds = []

    # Główny embed
    color = discord.Color.green() if not results.get("errors") else discord.Color.orange()
    embed = discord.Embed(
        title="🔄 LSPD — Synchronizacja ról",
        color=color,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text=f"Czas: {duration:.1f}s | {now}")

    updated  = results.get("updated", [])
    skipped  = results.get("skipped", [])
    nf       = results.get("not_found", [])
    errors   = results.get("errors", [])

    embed.add_field(name="✅ Zaktualizowano", value=str(len(updated)), inline=True)
    embed.add_field(name="⏭️ Bez zmian",     value=str(len(skipped)), inline=True)
    embed.add_field(name="❓ Nie znaleziono", value=str(len(nf)),      inline=True)

    if errors:
        embed.add_field(
            name="❌ Błędy",
            value="\n".join(errors[:5]) + ("..." if len(errors) > 5 else ""),
            inline=False
        )

    embeds.append(embed)

    # Drugi embed z listą zmian (jeśli są)
    if updated:
        changes_text = "\n".join(f"• {u}" for u in updated[:20])
        if len(updated) > 20:
            changes_text += f"\n... i {len(updated)-20} więcej"
        embed2 = discord.Embed(
            title="📋 Lista zmian",
            description=changes_text,
            color=discord.Color.blue()
        )
        embeds.append(embed2)

    return embeds

# ─── AUTO-SYNC TASK ───────────────────────────────────────────────────────────
@tasks.loop(minutes=SYNC_INTERVAL_MIN)
async def auto_sync():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        log.warning(f"Nie znaleziono serwera o ID {GUILD_ID}")
        return

    log.info(f"Auto-sync start (co {SYNC_INTERVAL_MIN} min)...")
    start = asyncio.get_event_loop().time()
    results = await sync_roles(guild)
    duration = asyncio.get_event_loop().time() - start

    upd = len(results.get("updated", []))
    log.info(f"Auto-sync done: {upd} zmian, {len(results.get('errors',[]))} błędów, {duration:.1f}s")

    # Wyślij raport na kanał logów jeśli ustawiony
    if LOG_CHANNEL_ID:
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if channel and upd > 0:
            for embed in format_report(results, duration):
                await channel.send(embed=embed)

@auto_sync.before_loop
async def before_sync():
    await bot.wait_until_ready()

# ─── SLASH COMMANDS ───────────────────────────────────────────────────────────
@tree.command(
    name="sync",
    description="Ręczna synchronizacja ról LSPD z bazą danych",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.checks.has_permissions(manage_roles=True)
async def cmd_sync(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    start = asyncio.get_event_loop().time()
    results = await sync_roles(interaction.guild)
    duration = asyncio.get_event_loop().time() - start

    if "error" in results:
        await interaction.followup.send(f"❌ {results['error']}", ephemeral=True)
        return

    embeds = format_report(results, duration)
    await interaction.followup.send(embeds=embeds)

@cmd_sync.error
async def sync_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Nie masz uprawnień do tej komendy.", ephemeral=True)

@tree.command(
    name="status",
    description="Sprawdź status bota i połączenie z bazą",
    guild=discord.Object(id=GUILD_ID)
)
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    officers = await fetch_officers()
    embed = discord.Embed(title="🤖 LSPD Bot — Status", color=discord.Color.blue())
    embed.add_field(name="📡 Baza danych",   value=f"{'✅ OK' if officers else '❌ Błąd'} ({len(officers)} FP)", inline=False)
    embed.add_field(name="🔄 Auto-sync",     value=f"Co {SYNC_INTERVAL_MIN} minut", inline=True)
    embed.add_field(name="👥 Członków",      value=str(interaction.guild.member_count), inline=True)
    embed.add_field(name="⏱️ Następny sync", value=f"<t:{int((datetime.utcnow().timestamp() + auto_sync.next_iteration.timestamp() - datetime.utcnow().timestamp()))}:R>" if auto_sync.next_iteration else "—", inline=True)

    await interaction.followup.send(embed=embed)

@tree.command(
    name="kto",
    description="Sprawdź jaki stopień ma dana osoba w bazie",
    guild=discord.Object(id=GUILD_ID)
)
async def cmd_kto(interaction: discord.Interaction, member: discord.Member):
    officers = await fetch_officers()
    name_lower = member.name.lower()
    disp_lower = member.display_name.lower()

    found = None
    for o in officers:
        nick = (o.get("nick") or "").strip().lower()
        # Sprawdź najpierw display_name (nick na serwerze), potem username
        if nick == disp_lower or nick == name_lower:
            found = o
            break

    if not found:
        await interaction.response.send_message(
            f"❓ Nie znaleziono **{member.display_name}** w bazie LSPD.",
            ephemeral=True
        )
        return

    status = "🔴 ZAWIESZONY" if found.get("suspended") else ("🟡 URLOP" if found.get("onLeave") else "🟢 AKTYWNY")
    units = [u.upper() for u in ["swat","iad","ftd"] if found.get(u)]

    embed = discord.Embed(title=f"👮 {found.get('name')}", color=discord.Color.blue())
    embed.add_field(name="Stopień",  value=found.get("rank","—"),         inline=True)
    embed.add_field(name="Odznaka", value=f"#{found.get('badge','—')}",   inline=True)
    embed.add_field(name="Status",  value=status,                          inline=True)
    if units:
        embed.add_field(name="Jednostki", value=", ".join(units), inline=False)

    await interaction.response.send_message(embed=embed)

# ─── EVENTS ───────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Bot zalogowany jako {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync(guild=discord.Object(id=GUILD_ID))
        log.info(f"Zsynchronizowano {len(synced)} komend slash")
    except Exception as e:
        log.error(f"Błąd sync komend: {e}")
    auto_sync.start()
    log.info(f"Auto-sync uruchomiony co {SYNC_INTERVAL_MIN} min")

# ─── START ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        log.error("Brak DISCORD_TOKEN w zmiennych środowiskowych!")
        exit(1)
    if not GUILD_ID:
        log.error("Brak GUILD_ID w zmiennych środowiskowych!")
        exit(1)
    bot.run(DISCORD_TOKEN)
