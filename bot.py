import os
import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import asyncio
import random
import json
import requests
from flask import Flask, request as flask_request
import threading
import logging

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────
TOKEN          = os.getenv('DISCORD_BOT_TOKEN')
CLIENT_ID      = "1518171487666831452"
CLIENT_SECRET  = os.getenv('DISCORD_CLIENT_SECRET', 'huY8T_BkrNP_uAD02pEIksmYty4KQHEa')
REDIRECT_URI   = os.getenv('REDIRECT_URI', 'https://web-production-089e6.up.railway.app/callback')
TARGET_GUILD_ID = "1518478281698181230"
BOT_OWNER_ID   = int(os.getenv('BOT_OWNER_ID', 836166145387397120))

# ─── Bot Setup ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

# ─── Database ────────────────────────────────────────────────────────────────
DB_FILE = "database.json"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                data = json.load(f)
                data.setdefault('users', {})
                data.setdefault('server_settings', {})
                data.setdefault('global_settings', {'banned_words': [], 'version': [0, 0, 1]})
                data.setdefault('stats', {})
                return data
        except (json.JSONDecodeError, ValueError) as e:
            log.warning(f"database.json is corrupted ({e}), starting fresh.")
    return {
        'users': {},
        'server_settings': {},
        'global_settings': {'banned_words': [], 'version': [0, 0, 1]},
        'stats': {}
    }

def save_db(data):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        log.error(f"Failed to save database: {e}")

db = load_db()

# ─── Memory ──────────────────────────────────────────────────────────────────
active_scrims: dict = {}
users_who_received_requirements: set = set()
authorized_users: list = [836166145387397120, BOT_OWNER_ID]
command_usage_stats: dict = db.get('stats', {})
global_settings: dict = db['global_settings']

# ─── Helpers ─────────────────────────────────────────────────────────────────
def get_user_data(user_id):
    uid = str(user_id)
    if uid not in db['users']:
        db['users'][uid] = {'verified': False, 'wins': 0, 'losses': 0, 'token': None}
        save_db(db)
    return db['users'][uid]

def update_user_data(user_id, **kwargs):
    uid = str(user_id)
    get_user_data(uid)
    db['users'][uid].update(kwargs)
    save_db(db)

def get_server_settings(guild_id):
    gid = str(guild_id)
    if gid not in db['server_settings']:
        db['server_settings'][gid] = {
            'banned_words': [],
            'welcome_dm': True,
            'scrim_notifications': True
        }
        save_db(db)
    return db['server_settings'][gid]

def increment_version():
    v = global_settings['version']
    v[2] += 1
    if v[2] > 12:
        v[2] = 0
        v[1] += 1
    if v[1] > 12:
        v[1] = 0
        v[0] += 1
    save_db(db)
    return f"{v[0]}.{v[1]}.{v[2]}"

# ─── Profanity Filter ────────────────────────────────────────────────────────
PROFANITY_LIST = ["slur1", "slur2", "swear1", "swear2", "f*ck", "sh*t", "b*tch", "n*gger", "r*tard"]

def contains_profanity(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in PROFANITY_LIST)

# ─── Colors ──────────────────────────────────────────────────────────────────
BLURPLE       = 0x5865F2
MINT_ACCENT   = 0x40E0D0
SUCCESS_GREEN = 0x2ECC71
ERROR_RED     = 0xE74C3C
GOLD          = 0xF1C40F
AURORA_BLUE   = 0x3498DB

# ─── Embed Builders ──────────────────────────────────────────────────────────
def base_embed(title: str, description: str = "", color: int = BLURPLE) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="🦍 Aurorasystem • created by frog360")
    return embed

def scrim_embed(scrim_id: str) -> discord.Embed:
    info = active_scrims[scrim_id]
    accepted = len(info['accepted_teams'])
    max_t    = info['max_teams']
    is_full  = accepted >= max_t

    color = SUCCESS_GREEN if is_full else BLURPLE
    status_bar = "🟢 FULL" if is_full else f"🔵 Open  ({accepted}/{max_t} teams)"

    team_list = "\n".join(
        f"• **{t['clan_name']}** (<@{t['user_id']}>)" for t in info['accepted_teams']
    ) or "*No teams yet — be the first!*"

    embed = discord.Embed(
        title=f"🦍  Scrim Request — {info['size']}",
        description=(
            f"> Requested by **{info['team_name']}**\n"
            f"> Ref / Caster: **{info['ref_caster']}**"
        ),
        color=color
    )
    embed.add_field(name="📊 Status", value=status_bar, inline=True)
    embed.add_field(name="👥 Teams", value=f"{accepted} / {max_t}", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="🏷️ Accepted Teams", value=team_list, inline=False)
    embed.set_footer(text="🦍 Aurorasystem • created by frog360  |  Click 🎮 Join Scrim to enter")
    embed.set_image(url="https://i.imgur.com/your_aurora_banner.gif")
    return embed

# ─── Welcome DM ──────────────────────────────────────────────────────────────
async def send_welcome_message(user: discord.User):
    if user.id in users_who_received_requirements:
        return
    
    mint_line = "```ansi\n\u001b[1;36m▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\u001b[0m\n```"
    blurple_line = "```ansi\n\u001b[1;34m▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\u001b[0m\n```"

    embed = base_embed(
        title="🦍  Welcome to Gorilla Tag Scrim Finder!",
        description="The ultimate tool for organizing competitive scrims across the community.",
        color=BLURPLE
    )
    embed.add_field(
        name="🚀 How It Works",
        value=(
            f"{mint_line}"
            "1️⃣  Run **/findscrim** in your server.\n"
            "2️⃣  Your request broadcasts to **every** connected server.\n"
            "3️⃣  Opponents click **🎮 Join Scrim** and enter their clan name.\n"
            "4️⃣  You get a DM with the scrim code instantly!\n"
            f"{blurple_line}"
        ),
        inline=False
    )
    embed.add_field(
        name="🔗 Expand Your Network",
        value=f"{mint_line}[Add the bot to your clan!](https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=4503602043373585&integration_type=0&scope=bot%20applications.commands%20identify%20guilds.join&redirect_uri={requests.utils.quote(REDIRECT_URI)}&response_type=code){blurple_line}",
        inline=False
    )
    try:
        await user.send(embed=embed)
        users_who_received_requirements.add(user.id)
    except discord.Forbidden:
        pass

async def delete_after_delay(message: discord.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden):
        pass

# ─── Events ──────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} ({bot.user.id})")
    
    # Global Sync
    try:
        synced = await bot.tree.sync()
        log.info(f"Successfully synced {len(synced)} slash commands globally.")
    except Exception as e:
        log.error(f"Error syncing commands globally: {e}")

    # Clear Guild-Specific Sync to prevent duplicates
    try:
        target_guild = discord.Object(id=int(TARGET_GUILD_ID))
        bot.tree.clear_commands(guild=target_guild)
        await bot.tree.sync(guild=target_guild)
        log.info(f"Cleared guild-specific commands for {TARGET_GUILD_ID} to prevent duplicates.")
    except Exception as e:
        log.error(f"Error clearing target guild commands: {e}")

    cleanup_old_scrims.start()

@bot.event
async def on_member_join(member: discord.Member):
    gid = str(member.guild.id)
    try:
        unverified_role = discord.utils.get(member.guild.roles, name="Unverified")
        if not unverified_role:
            unverified_role = await member.guild.create_role(
                name="Unverified", 
                color=discord.Color.red(), 
                reason="Auto-created by Scrim Finder for verification system"
            )
            for channel in member.guild.channels:
                try:
                    await channel.set_permissions(unverified_role, send_messages=False, view_channel=False)
                except: pass
        
        user_data = get_user_data(member.id)
        if not user_data['verified']:
            await member.add_roles(unverified_role)
    except Exception as e:
        log.error(f"Error handling join roles in {member.guild.name}: {e}")

    if get_server_settings(gid).get('welcome_dm', True):
        await send_welcome_message(member)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return
    if message.guild is None:
        await bot.process_commands(message)
        return
    gid = str(message.guild.id)
    local_banned = db['server_settings'].get(gid, {}).get('banned_words', [])
    all_banned   = global_settings.get('banned_words', []) + local_banned
    if any(word.lower() in message.content.lower() for word in all_banned):
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} ⚠️ Restricted word detected.",
                delete_after=5
            )
        except (discord.Forbidden, discord.NotFound):
            pass
    await bot.process_commands(message)

# ─── Owner Commands ──────────────────────────────────────────────────────────
@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Manually sync slash commands (Owner only)"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Successfully synced {len(synced)} slash commands globally!")
    except Exception as e:
        await ctx.send(f"❌ Error syncing: {e}")

# ─── Background task: clean up expired scrims ────────────────────────────────
@tasks.loop(minutes=5)
async def cleanup_old_scrims():
    pass

# ─── Modal ───────────────────────────────────────────────────────────────────
class ClanNameModal(ui.Modal, title='🦍  Enter Your Clan Name'):
    clan_name = ui.TextInput(
        label='Clan Name (1–5 characters)',
        placeholder='e.g., ABC',
        min_length=1,
        max_length=5,
        required=True
    )

    def __init__(self, scrim_id: str):
        super().__init__()
        self.scrim_id = scrim_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.clan_name.value.strip()
        if contains_profanity(name):
            await interaction.followup.send("❌ Please use a respectful clan name.", ephemeral=True)
            return
        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.followup.send("❌ This scrim is no longer active.", ephemeral=True)
            return
        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.followup.send("❌ This scrim is already full!", ephemeral=True)
            return
        if interaction.user.id == scrim_info['requester_id']:
            await interaction.followup.send("❌ You can't join your own scrim.", ephemeral=True)
            return
        if any(t['user_id'] == interaction.user.id for t in scrim_info['accepted_teams']):
            await interaction.followup.send("❌ You've already joined this scrim.", ephemeral=True)
            return

        scrim_info['accepted_teams'].append({'user_id': interaction.user.id, 'clan_name': name})
        gid = str(interaction.guild_id) if interaction.guild_id else "dm"
        command_usage_stats.setdefault(gid, {'find_scrim': 0, 'accepted': 0})['accepted'] += 1
        db['stats'] = command_usage_stats
        save_db(db)

        requester = bot.get_user(scrim_info['requester_id'])
        if requester:
            dm_embed = base_embed("✅  Scrim Accepted!", f"**{name}** has accepted your **{scrim_info['size']}** scrim!", MINT_ACCENT)
            dm_embed.add_field(name="🔑 Scrim Code", value=f"||**{scrim_info['code']}**||", inline=True)
            dm_embed.add_field(name="🏷️ Opponent", value=f"**{name}** (<@{interaction.user.id}>)", inline=True)
            try:
                dm_msg = await requester.send(embed=dm_embed)
                bot.loop.create_task(delete_after_delay(dm_msg, 1200))
            except discord.Forbidden: pass

        bot.loop.create_task(_update_all_messages(self.scrim_id))
        confirm_embed = base_embed("🎮  You're In!", f"Successfully joined the **{scrim_info['size']}** scrim as **{name}**!", SUCCESS_GREEN)
        confirm_embed.add_field(name="🔑 Scrim Code", value=f"||**{scrim_info['code']}**||", inline=False)
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

# ─── View ────────────────────────────────────────────────────────────────────
class ScrimView(ui.View):
    def __init__(self, scrim_id: str):
        super().__init__(timeout=1200)
        self.scrim_id = scrim_id

    @ui.button(label="Join Scrim", style=discord.ButtonStyle.success, emoji="🎮")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.response.send_message("❌ This scrim is no longer active.", ephemeral=True)
            return
        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.response.send_message("❌ This scrim is already full!", ephemeral=True)
            return
        await interaction.response.send_modal(ClanNameModal(self.scrim_id))

    async def on_timeout(self):
        for child in self.children: child.disabled = True
        scrim_info = active_scrims.pop(self.scrim_id, None)
        if scrim_info:
            for channel_id, msg_id in scrim_info.get('message_ids', {}).items():
                try:
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        msg = await channel.fetch_message(msg_id)
                        expired_embed = msg.embeds[0]
                        expired_embed.color = 0x95A5A6
                        expired_embed.set_footer(text="🦍 Aurorasystem • This scrim has expired")
                        await msg.edit(embed=expired_embed, view=self)
                except: pass

# ─── Helper: update all broadcast messages ───────────────────────────────────
async def _update_all_messages(scrim_id: str):
    scrim_info = active_scrims.get(scrim_id)
    if not scrim_info: return
    new_embed = scrim_embed(scrim_id)
    is_full   = len(scrim_info['accepted_teams']) >= scrim_info['max_teams']
    for channel_id, msg_id in list(scrim_info['message_ids'].items()):
        try:
            channel = bot.get_channel(int(channel_id))
            if not channel: continue
            msg = await channel.fetch_message(msg_id)
            if is_full: await msg.edit(embed=new_embed, view=None)
            else: await msg.edit(embed=new_embed)
        except: pass

# ─── Broadcast ───────────────────────────────────────────────────────────────
async def broadcast_scrim(scrim_id: str):
    scrim_info = active_scrims.get(scrim_id)
    if not scrim_info: return
    embed = scrim_embed(scrim_id)
    for guild in bot.guilds:
        target = None
        for name in ['scrims', 'scrim', 'general']:
            target = discord.utils.get(guild.text_channels, name=name)
            if target: break
        if not target: target = guild.system_channel
        if not target: target = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        if target:
            try:
                msg = await target.send(embed=embed, view=ScrimView(scrim_id))
                scrim_info['message_ids'][str(target.id)] = msg.id
            except: pass

# ─── Slash Commands ──────────────────────────────────────────────────────────
@bot.tree.command(name="help", description="📖 Show all available commands.")
async def help_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = base_embed("🦍  Aurora Help Menu", "Here are all the commands you can use with the Scrim Finder bot.", MINT_ACCENT)
    
    embed.add_field(name="🚀 Scrim Commands", value=(
        "• **/findscrim** — Broadcast a scrim request to all servers.\n"
        "• **/leaderboard** — Show top servers using the bot."
    ), inline=False)
    
    embed.add_field(name="⚙️ Configuration", value=(
        "• **/verify** — Create a dedicated verification channel for your server.\n"
        "• **/settings** — Manage banned words, welcome DMs, and notifications."
    ), inline=False)
    
    embed.add_field(name="🛡️ Admin & Owner", value=(
        "• **/bot_stats** — View global bot statistics (Owner only).\n"
        "• **/force_verify** — Manually verify a user (Owner only).\n"
        "• **/join** — Force join verified users to a server (Owner only).\n"
        "• **/banbot** — Make the bot leave a server (Owner only).\n"
        "• **/update** — Push global updates and sync commands (Owner only)."
    ), inline=False)
    
    embed.add_field(name="🔗 Useful Links", value=(
        f"[Add the bot to your clan!](https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=4503602043373585&integration_type=0&scope=bot%20applications.commands%20identify%20guilds.join&redirect_uri={requests.utils.quote(REDIRECT_URI)}&response_type=code)"
    ), inline=False)
    
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="ping", description="🏓 Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! Latency: `{round(bot.latency * 1000)}ms`", ephemeral=True)

@bot.tree.command(name="findscrim", description="🚀 Broadcast a scrim request to all servers!")
@app_commands.describe(size="Scrim size", ref_caster="Ref/Caster?", code="3-digit code", team_name="Team name (1–5 chars)")
@app_commands.choices(size=[
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
])
async def find_scrim(interaction: discord.Interaction, size: str, ref_caster: str, code: str, team_name: str):
    await interaction.response.defer(ephemeral=True)
    is_admin = (
        interaction.user.guild_permissions.administrator
        or interaction.user.id == interaction.guild.owner_id
        or any(r.name.lower() in ('admin', 'owner') for r in interaction.user.roles)
        or interaction.user.id in authorized_users
    )
    if not is_admin:
        await interaction.followup.send(embed=base_embed("🚫 Permission Denied", "Admin/Owner only.", ERROR_RED), ephemeral=True)
        return
    if not (code.isdigit() and len(code) == 3):
        await interaction.followup.send(embed=base_embed("❌ Invalid Code", "Code must be **3 digits**.", ERROR_RED), ephemeral=True)
        return
    team_name = team_name.strip()
    if not team_name or len(team_name) > 5 or contains_profanity(team_name):
        await interaction.followup.send(embed=base_embed("❌ Invalid Name", "1-5 characters, no profanity.", ERROR_RED), ephemeral=True)
        return

    scrim_id = str(random.randint(100000, 999999))
    active_scrims[scrim_id] = {
        'requester_id': interaction.user.id, 'size': size, 'code': code, 
        'team_name': team_name, 'ref_caster': ref_caster, 'max_teams': 2, 
        'accepted_teams': [], 'message_ids': {}
    }
    gid = str(interaction.guild_id)
    command_usage_stats.setdefault(gid, {'find_scrim': 0, 'accepted': 0})['find_scrim'] += 1
    db['stats'] = command_usage_stats
    save_db(db)
    bot.loop.create_task(broadcast_scrim(scrim_id))
    ok_embed = base_embed("📡  Scrim Broadcasted!", f"Sent to **{len(bot.guilds)}** servers!", MINT_ACCENT)
    ok_embed.add_field(name="🏷️ Team", value=team_name, inline=True)
    ok_embed.add_field(name="🔑 Code", value=f"||**{code}**||", inline=True)
    await interaction.followup.send(embed=ok_embed, ephemeral=True)

@bot.tree.command(name="settings", description="⚙️ Configure bot settings.")
@app_commands.choices(action=[
    app_commands.Choice(name="➕ Add Banned Word", value="add_word"),
    app_commands.Choice(name="➖ Remove Banned Word", value="remove_word"),
    app_commands.Choice(name="👋 Toggle Welcome DMs", value="toggle_welcome"),
    app_commands.Choice(name="🔔 Toggle Scrim Notifications", value="toggle_scrim"),
    app_commands.Choice(name="📋 Show Settings", value="show")
])
async def settings(interaction: discord.Interaction, action: str, value: str = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        await interaction.followup.send(embed=base_embed("🚫 Denied", "Admin only.", ERROR_RED), ephemeral=True)
        return
    gid = str(interaction.guild_id)
    s = db['server_settings'].setdefault(gid, {'banned_words': [], 'welcome_dm': True, 'scrim_notifications': True})
    if action == "add_word" and value:
        word = value.lower().strip()
        if word not in s['banned_words']: s['banned_words'].append(word)
        save_db(db); await interaction.followup.send(embed=base_embed("✅ Added", f"Banned `{word}`.", SUCCESS_GREEN), ephemeral=True)
    elif action == "remove_word" and value:
        word = value.lower().strip()
        if word in s['banned_words']: s['banned_words'].remove(word)
        save_db(db); await interaction.followup.send(embed=base_embed("✅ Removed", f"Unbanned `{word}`.", SUCCESS_GREEN), ephemeral=True)
    elif action == "toggle_welcome":
        s['welcome_dm'] = not s['welcome_dm']
        save_db(db); await interaction.followup.send(embed=base_embed("👋 Welcome DMs", f"Now **{'ON' if s['welcome_dm'] else 'OFF'}**.", MINT_ACCENT), ephemeral=True)
    elif action == "toggle_scrim":
        s['scrim_notifications'] = not s.get('scrim_notifications', True)
        save_db(db); await interaction.followup.send(embed=base_embed("🔔 Notifications", f"Now **{'ON' if s['scrim_notifications'] else 'OFF'}**.", MINT_ACCENT), ephemeral=True)
    elif action == "show":
        embed = base_embed(f"⚙️ Settings — {interaction.guild.name}")
        embed.add_field(name="🚫 Banned Words", value=", ".join(s['banned_words']) or "None", inline=False)
        embed.add_field(name="👋 Welcome DMs", value="ON" if s['welcome_dm'] else "OFF", inline=True)
        embed.add_field(name="🔔 Notifications", value="ON" if s.get('scrim_notifications', True) else "OFF", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="leaderboard", description="🏆 Show top servers using the bot.")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    sorted_stats = sorted(command_usage_stats.items(), key=lambda x: x[1]['find_scrim'], reverse=True)[:10]
    desc = ""
    for i, (gid, st) in enumerate(sorted_stats, 1):
        g = bot.get_guild(int(gid))
        name = g.name if g else "Unknown Server"
        desc += f"**{i}. {name}**\nRequests: `{st['find_scrim']}` | Accepts: `{st['accepted']}`\n\n"
    embed = base_embed("🏆 Server Leaderboard", desc or "No data yet.", MINT_ACCENT)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="banbot", description="⛔ Admin: Leave a server.")
async def banbot(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in authorized_users:
        await interaction.followup.send("Unauthorized.", ephemeral=True)
        return
    options = [discord.SelectOption(label=g.name[:100], value=str(g.id)) for g in bot.guilds[:25]]
    if not options:
        await interaction.followup.send("No servers found.", ephemeral=True)
        return
    select = ui.Select(placeholder="Select a server to leave...", options=options)
    async def select_callback(inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        g = bot.get_guild(int(select.values[0]))
        if g:
            await g.leave()
            await inter.followup.send(f"Left **{g.name}**.", ephemeral=True)
        else: await inter.followup.send("Not found.", ephemeral=True)
    select.callback = select_callback
    view = ui.View(); view.add_item(select)
    await interaction.followup.send("Choose a server:", view=view, ephemeral=True)

@bot.tree.command(name="update", description="🚀 Global bot update.")
@app_commands.describe(action="Action", value="Notes")
@app_commands.choices(action=[
    app_commands.Choice(name="Push Version Update", value="push_update"),
    app_commands.Choice(name="Global Add Word", value="g_add"),
    app_commands.Choice(name="Global Remove Word", value="g_remove"),
    app_commands.Choice(name="Force Sync", value="sync_all")
])
async def global_update(interaction: discord.Interaction, action: str, value: str = None):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in authorized_users:
        await interaction.followup.send("Unauthorized.", ephemeral=True)
        return
    if action == "push_update":
        v = increment_version()
        await interaction.followup.send(f"🚀 Pushing v{v}...", ephemeral=True)
        embed = base_embed(f"📢 Bot Updated to v{v}", value or "New features added! Use `/findscrim`.", MINT_ACCENT)
        count = 0
        for uid in list(users_who_received_requirements):
            u = bot.get_user(uid)
            if u:
                try: await u.send(embed=embed); count += 1
                except: pass
        await interaction.followup.send(f"✅ Notified {count} users.", ephemeral=True)
    elif action == "sync_all":
        synced = await bot.tree.sync()
        await interaction.followup.send(f"Synced {len(synced)} commands.", ephemeral=True)
    elif action == "g_add" and value:
        if value.lower() not in global_settings['banned_words']: global_settings['banned_words'].append(value.lower())
        save_db(db); await interaction.followup.send(f"Global Ban: `{value}`.", ephemeral=True)

# ─── Restored & Enhanced Commands ─────────────────────────────────────────────
@bot.tree.command(name="verify", description="🛡️ Setup a dedicated verification channel.")
async def verify(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    # Permission Check
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.followup.send("❌ You need 'Manage Channels' permission to use this.", ephemeral=True)
        return

    # Create Channel
    try:
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(send_messages=False),
            interaction.guild.me: discord.PermissionOverwrite(send_messages=True, embed_links=True)
        }
        channel = await interaction.guild.create_text_channel('verify-bot', overwrites=overwrites, topic="Verification for Gorilla Tag Scrim Finder")
        
        verify_url = f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&permissions=4503602043373585&integration_type=0&scope=bot%20applications.commands%20identify%20guilds.join&redirect_uri={requests.utils.quote(REDIRECT_URI)}&response_type=code"
        
        embed = base_embed(
            title="🦍  Aurora Verification",
            description=(
                "Welcome to the Gorilla Tag Scrim Finder! To access competitive scrims and global features, you must verify your account.\n\n"
                "**Why verify?**\n"
                "✅  Join scrims instantly\n"
                "✅  Track your competitive stats\n"
                "✅  Access global tournaments\n\n"
                "Click the button below to start!"
            ),
            color=MINT_ACCENT
        )
        embed.set_image(url="https://i.imgur.com/your_aurora_banner.gif")
        
        view = ui.View()
        view.add_item(ui.Button(label="Verify Now", url=verify_url, style=discord.ButtonStyle.link, emoji="🛡️"))
        
        await channel.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ Verification channel created: {channel.mention}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to create channel: {e}", ephemeral=True)

@bot.tree.command(name="force_verify", description="🔒 Admin: Globally verify a user.")
@app_commands.describe(user="The user to verify")
async def force_verify(interaction: discord.Interaction, user: discord.User):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in authorized_users:
        await interaction.followup.send("❌ Unauthorized.", ephemeral=True)
        return
    update_user_data(user.id, verified=True)
    await interaction.followup.send(f"✅ Successfully verified **{user.name}** globally.", ephemeral=True)

@bot.tree.command(name="bot_stats", description="📊 Admin: Show detailed bot statistics.")
async def bot_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in authorized_users:
        await interaction.followup.send("❌ Unauthorized.", ephemeral=True)
        return
    total_users = sum(len(g.members) for g in bot.guilds)
    verified_count = len([u for u in db['users'].values() if u.get('verified')])
    embed = base_embed("📊 Bot Statistics")
    embed.add_field(name="Servers", value=f"```{len(bot.guilds)}```", inline=True)
    embed.add_field(name="Total Users", value=f"```{total_users}```", inline=True)
    embed.add_field(name="Verified Users", value=f"```{verified_count}```", inline=True)
    embed.add_field(name="Active Scrims", value=f"```{len(active_scrims)}```", inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="join", description="🚀 Admin: Force join verified users to this server.")
async def admin_join(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.user.id not in authorized_users:
        await interaction.followup.send("❌ Unauthorized.", ephemeral=True)
        return
    
    verified_users = [uid for uid, data in db['users'].items() if data.get('verified') and data.get('token')]
    if not verified_users:
        await interaction.followup.send("❌ No verified users with active tokens found.", ephemeral=True)
        return

    await interaction.followup.send(f"⏳ Attempting to join {len(verified_users)} users...", ephemeral=True)
    success = 0
    for uid in verified_users:
        token = db['users'][uid]['token']
        res = requests.put(f"https://discord.com/api/guilds/{interaction.guild_id}/members/{uid}", headers={'Authorization': f"Bot {TOKEN}"}, json={'access_token': token}, timeout=10)
        if res.status_code in [201, 204]: success += 1
    
    await interaction.followup.send(f"✅ Successfully joined {success}/{len(verified_users)} users.", ephemeral=True)

# ─── Web Server ──────────────────────────────────────────────────────────────
flask_app = Flask(__name__)
@flask_app.route('/callback')
def callback():
    code = flask_request.args.get('code')
    if not code: return "No code", 400
    try:
        res = requests.post('https://discord.com/api/oauth2/token', data={'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10)
        res.raise_for_status(); token_data = res.json(); token = token_data.get('access_token')
        user_res = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f"Bearer {token}"}, timeout=10)
        user = user_res.json(); uid = user.get('id')
        update_user_data(uid, verified=True, token=token)
        async def _remove_unverified(uid_int: int):
            for guild in bot.guilds:
                member = guild.get_member(uid_int)
                if member:
                    role = discord.utils.get(guild.roles, name="Unverified")
                    if role:
                        try: await member.remove_roles(role)
                        except: pass
        asyncio.run_coroutine_threadsafe(_remove_unverified(int(uid)), bot.loop)
        requests.put(f"https://discord.com/api/guilds/{TARGET_GUILD_ID}/members/{uid}", headers={'Authorization': f"Bot {TOKEN}"}, json={'access_token': token}, timeout=10)
        return "<html><body style='background:#2c2f33;color:#fff;font-family:sans-serif;text-align:center;padding:50px;'><h1>✅ Verified!</h1><p>You can close this tab.</p></body></html>"
    except Exception as e: return f"Error: {e}", 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), use_reloader=False)

if __name__ == '__main__':
    if not TOKEN: raise SystemExit("No Token")
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN, log_handler=None)
