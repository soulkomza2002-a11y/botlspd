import os
import nextcord
from nextcord.ext import commands, tasks
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
LOG_CHANNEL_ID    = int(os.getenv("LOG_CHANNEL_ID", "0"))

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
}
ALL_LSPD_ROLES = set(RANK_TO_ROLE.values())

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

# ─── SYNC LOGIC ───────────────────────────────────────────────────────────────
async def sync_roles(guild: nextcord.Guild) -> dict:
    officers = await fetch_officers()
    if not officers:
        return {"error": "Nie udało się pobrać danych z bazy"}

    nick_map = {}
    for o in officers:
        nick = (o.get("nick") or "").strip().lower()
        rank = o.get("rank", "")
        if nick and rank in RANK_TO_ROLE:
            nick_map[nick] = rank

    results = {"updated": [], "skipped": [], "not_found": [], "errors": []}
    guild_roles = {r.name: r for r in guild.roles}

    for member in guild.members:
        if member.bot:
            continue

        display_lower  = member.display_name.lower()
        username_lower = member.name.lower()
        matched_rank   = nick_map.get(display_lower) or nick_map.get(username_lower)

        if not matched_rank:
            results["not_found"].append(member.display_name)
            continue

        target_role_name = RANK_TO_ROLE[matched_rank]
        target_role = guild_roles.get(target_role_name)

        if not target_role:
            results["errors"].append(f"Brak roli '{target_role_name}' na serwerze")
            continue

        current_lspd = [r for r in member.roles if r.name in ALL_LSPD_ROLES]
        has_target   = any(r.name == target_role_name for r in member.roles)

        if has_target and len(current_lspd) == 1:
            results["skipped"].append(member.display_name)
            continue

        try:
            to_remove = [r for r in member.roles if r.name in ALL_LSPD_ROLES and r.name != target_role_name]
            if to_remove:
                await member.remove_roles(*to_remove, reason="LSPD Bot sync")
            if not has_target:
                await member.add_roles(target_role, reason="LSPD Bot sync")
            results["updated"].append(f"{member.display_name} → {target_role_name}")
            log.info(f"[SYNC] {member.display_name} → {target_role_name}")
        except nextcord.Forbidden:
            results["errors"].append(f"Brak uprawnień: {member.display_name}")
        except Exception as e:
            results["errors"].append(f"{member.display_name}: {e}")

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

@auto_sync.before_loop
async def before_auto_sync():
    await bot.wait_until_ready()

# ─── /sync ────────────────────────────────────────────────────────────────────
@nextcord.slash_command(name="sync", description="Ręczna synchronizacja ról LSPD", guild_ids=[GUILD_ID])
async def cmd_sync(interaction: nextcord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        await interaction.response.send_message("❌ Potrzebujesz uprawnienia **Zarządzaj rolami**.", ephemeral=True)
        return
    await interaction.response.defer()
    t = asyncio.get_event_loop().time()
    results = await sync_roles(interaction.guild)
    duration = asyncio.get_event_loop().time() - t
    if "error" in results:
        await interaction.followup.send(f"❌ {results['error']}")
        return
    for embed in build_embeds(results, duration):
        await interaction.followup.send(embed=embed)

bot.add_application_command(cmd_sync)

# ─── /status ──────────────────────────────────────────────────────────────────
@nextcord.slash_command(name="status", description="Status bota LSPD", guild_ids=[GUILD_ID])
async def cmd_status(interaction: nextcord.Interaction):
    await interaction.response.defer()
    officers = await fetch_officers()
    embed = nextcord.Embed(title="🤖 LSPD Bot — Status", color=nextcord.Color.blue())
    embed.add_field(name="📡 Baza danych", value=f"{'✅ OK' if officers else '❌ Błąd'} ({len(officers)} FP)", inline=False)
    embed.add_field(name="🔄 Auto-sync",   value=f"Co {SYNC_INTERVAL_MIN} min", inline=True)
    embed.add_field(name="👥 Członków",    value=str(interaction.guild.member_count), inline=True)
    await interaction.followup.send(embed=embed)

bot.add_application_command(cmd_status)

# ─── /kto ─────────────────────────────────────────────────────────────────────
@nextcord.slash_command(name="kto", description="Sprawdź stopień osoby w bazie LSPD", guild_ids=[GUILD_ID])
async def cmd_kto(interaction: nextcord.Interaction, member: nextcord.Member):
    await interaction.response.defer()
    officers = await fetch_officers()
    disp  = member.display_name.lower()
    uname = member.name.lower()
    found = next((o for o in officers if (o.get("nick") or "").strip().lower() in (disp, uname)), None)
    if not found:
        await interaction.followup.send(f"❓ **{member.display_name}** nie ma w bazie LSPD.", ephemeral=True)
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

bot.add_application_command(cmd_kto)

# ─── ON READY ─────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"✅ Bot online: {bot.user} | Serwer: {GUILD_ID} | Sync co {SYNC_INTERVAL_MIN} min")
    if not auto_sync.is_running():
        auto_sync.start()

# ─── START ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    for var, val in [("DISCORD_TOKEN", DISCORD_TOKEN), ("GUILD_ID", GUILD_ID),
                     ("JSONBIN_BIN_ID", JSONBIN_BIN_ID), ("JSONBIN_API_KEY", JSONBIN_API_KEY)]:
        if not val:
            log.error(f"Brak zmiennej środowiskowej: {var}")
            exit(1)
    bot.run(DISCORD_TOKEN)
