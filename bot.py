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
BOT_OWNER_ID   = int(os.getenv('BOT_OWNER_ID', 0))

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
                # Ensure all required top-level keys exist
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
authorized_users: list = [836166145387397120]
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
    get_user_data(uid)          # ensure entry exists
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
    embed.add_field(name="\u200b", value="\u200b", inline=True)   # spacer
    embed.add_field(name="🏷️ Accepted Teams", value=team_list, inline=False)
    embed.set_footer(text="🦍 Aurorasystem • created by frog360  |  Click 🎮 Join Scrim to enter")
    return embed

# ─── Welcome DM ──────────────────────────────────────────────────────────────
async def send_welcome_message(user: discord.User):
    if user.id in users_who_received_requirements:
        return
    embed = base_embed(
        title="🦍  Welcome to Gorilla Tag Scrim Finder!",
        description="Organize competitive scrims in seconds — across every server the bot is in.",
        color=BLURPLE
    )
    embed.add_field(
        name="🚀 How It Works",
        value=(
            "1️⃣  Run **/findscrim** in your server.\n"
            "2️⃣  Your request broadcasts to **every** connected server.\n"
            "3️⃣  Opponents click **🎮 Join Scrim** and enter their clan name.\n"
            "4️⃣  You get a DM with the scrim code instantly!"
        ),
        inline=False
    )
    embed.add_field(
        name="⚙️ Commands",
        value="`/findscrim` · `/settings`",
        inline=False
    )
    try:
        await user.send(embed=embed)
        users_who_received_requirements.add(user.id)
    except discord.Forbidden:
        pass   # DMs closed — that's fine

async def delete_after_delay(message: discord.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden):
        pass

# ─── Events ──────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        log.error(f"Failed to sync commands: {e}")
    cleanup_old_scrims.start()

@bot.event
async def on_guild_join(guild: discord.Guild):
    log.info(f"Joined guild: {guild.name} ({guild.id})")

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
                f"{message.author.mention} ⚠️ That word is restricted here.",
                delete_after=5
            )
        except (discord.Forbidden, discord.NotFound):
            pass
    await bot.process_commands(message)

# ─── Background task: clean up expired scrims ────────────────────────────────
@tasks.loop(minutes=5)
async def cleanup_old_scrims():
    # active_scrims entries don't store timestamps; ScrimView has a 1200s timeout.
    # This loop is a safety net — nothing to do unless we add timestamps later.
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
            await interaction.followup.send(
                "❌ Please use a respectful clan name.", ephemeral=True
            )
            return

        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.followup.send(
                "❌ This scrim is no longer active.", ephemeral=True
            )
            return

        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.followup.send(
                "❌ This scrim is already full!", ephemeral=True
            )
            return

        if interaction.user.id == scrim_info['requester_id']:
            await interaction.followup.send(
                "❌ You can't join your own scrim.", ephemeral=True
            )
            return

        # Check if user already joined
        if any(t['user_id'] == interaction.user.id for t in scrim_info['accepted_teams']):
            await interaction.followup.send(
                "❌ You've already joined this scrim.", ephemeral=True
            )
            return

        scrim_info['accepted_teams'].append({
            'user_id': interaction.user.id,
            'clan_name': name
        })

        # Stats
        gid = str(interaction.guild_id) if interaction.guild_id else "dm"
        command_usage_stats.setdefault(gid, {'find_scrim': 0, 'accepted': 0})['accepted'] += 1
        db['stats'] = command_usage_stats
        save_db(db)

        # DM the requester
        requester = bot.get_user(scrim_info['requester_id'])
        if requester:
            dm_embed = base_embed(
                title="✅  Scrim Accepted!",
                description=f"**{name}** has accepted your **{scrim_info['size']}** scrim!",
                color=MINT_ACCENT
            )
            dm_embed.add_field(
                name="🔑 Scrim Code",
                value=f"||**{scrim_info['code']}**||",
                inline=True
            )
            dm_embed.add_field(
                name="🏷️ Opponent",
                value=f"**{name}** (<@{interaction.user.id}>)",
                inline=True
            )
            dm_embed.set_footer(text="🦍 Aurorasystem • This DM auto-deletes in 20 minutes")
            try:
                dm_msg = await requester.send(embed=dm_embed)
                bot.loop.create_task(delete_after_delay(dm_msg, 1200))
            except discord.Forbidden:
                pass

        # Update all broadcast messages
        bot.loop.create_task(_update_all_messages(self.scrim_id))

        confirm_embed = base_embed(
            title="🎮  You're In!",
            description=f"Successfully joined the **{scrim_info['size']}** scrim as **{name}**!",
            color=SUCCESS_GREEN
        )
        confirm_embed.add_field(
            name="🔑 Scrim Code",
            value=f"||**{scrim_info['code']}**||",
            inline=False
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"ClanNameModal error: {error}", exc_info=True)
        try:
            await interaction.followup.send(
                "❌ Something went wrong. Please try again.", ephemeral=True
            )
        except Exception:
            pass

# ─── View ────────────────────────────────────────────────────────────────────
class ScrimView(ui.View):
    def __init__(self, scrim_id: str):
        super().__init__(timeout=1200)
        self.scrim_id = scrim_id

    @ui.button(label="Join Scrim", style=discord.ButtonStyle.success, emoji="🎮")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.response.send_message(
                "❌ This scrim is no longer active.", ephemeral=True
            )
            return
        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.response.send_message(
                "❌ This scrim is already full!", ephemeral=True
            )
            return
        await interaction.response.send_modal(ClanNameModal(self.scrim_id))

    async def on_timeout(self):
        # Disable the button and clean up when the view expires
        for child in self.children:
            child.disabled = True
        scrim_info = active_scrims.pop(self.scrim_id, None)
        if scrim_info:
            for channel_id, msg_id in scrim_info.get('message_ids', {}).items():
                try:
                    channel = bot.get_channel(int(channel_id))
                    if channel:
                        msg = await channel.fetch_message(msg_id)
                        expired_embed = scrim_embed(self.scrim_id) if self.scrim_id in active_scrims else msg.embeds[0]
                        expired_embed.color = 0x95A5A6  # grey = expired
                        expired_embed.set_footer(text="🦍 Aurorasystem • This scrim has expired")
                        await msg.edit(embed=expired_embed, view=self)
                except Exception:
                    pass

# ─── Helper: update all broadcast messages ───────────────────────────────────
async def _update_all_messages(scrim_id: str):
    scrim_info = active_scrims.get(scrim_id)
    if not scrim_info:
        return
    new_embed = scrim_embed(scrim_id)
    is_full   = len(scrim_info['accepted_teams']) >= scrim_info['max_teams']

    for channel_id, msg_id in list(scrim_info['message_ids'].items()):
        try:
            channel = bot.get_channel(int(channel_id))
            if not channel:
                continue
            msg = await channel.fetch_message(msg_id)
            if is_full:
                await msg.edit(embed=new_embed, view=None)
            else:
                await msg.edit(embed=new_embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        except Exception as e:
            log.warning(f"Failed to update message {msg_id}: {e}")

# ─── Broadcast ───────────────────────────────────────────────────────────────
async def broadcast_scrim(scrim_id: str):
    scrim_info = active_scrims.get(scrim_id)
    if not scrim_info:
        return
    embed = scrim_embed(scrim_id)
    view  = ScrimView(scrim_id)

    for guild in bot.guilds:
        target = None
        for name in ['scrims', 'scrim', 'general']:
            target = discord.utils.get(guild.text_channels, name=name)
            if target:
                break
        if not target:
            target = guild.system_channel
        if not target:
            target = next(
                (c for c in guild.text_channels
                 if c.permissions_for(guild.me).send_messages),
                None
            )
        if target:
            try:
                msg = await target.send(embed=embed, view=view)
                scrim_info['message_ids'][str(target.id)] = msg.id
            except (discord.Forbidden, discord.HTTPException) as e:
                log.warning(f"Could not send to {guild.name} #{target.name}: {e}")

# ─── /findscrim ──────────────────────────────────────────────────────────────
@bot.tree.command(name="findscrim", description="🚀 Broadcast a scrim request to all servers!")
@app_commands.describe(
    size="Scrim size",
    ref_caster="Do you need a ref or caster?",
    code="3-digit scrim code (e.g. 123)",
    team_name="Your team / clan name (1–5 chars)"
)
@app_commands.choices(size=[
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
])
async def find_scrim(
    interaction: discord.Interaction,
    size: str,
    ref_caster: str,
    code: str,
    team_name: str
):
    await interaction.response.defer(ephemeral=True)

    # Permission check
    is_admin = (
        interaction.user.guild_permissions.administrator
        or interaction.user.id == interaction.guild.owner_id
        or any(r.name.lower() in ('admin', 'owner') for r in interaction.user.roles)
        or interaction.user.id == BOT_OWNER_ID
    )
    if not is_admin:
        err = base_embed("🚫 Permission Denied", "Only **Admins** or **Owners** can post scrim requests.", ERROR_RED)
        await interaction.followup.send(embed=err, ephemeral=True)
        return

    # Validate code
    if not (code.isdigit() and len(code) == 3):
        err = base_embed("❌ Invalid Code", "The scrim code must be exactly **3 digits** (e.g. `123`).", ERROR_RED)
        await interaction.followup.send(embed=err, ephemeral=True)
        return

    # Validate team name
    team_name = team_name.strip()
    if not team_name or len(team_name) > 5:
        err = base_embed("❌ Invalid Team Name", "Team name must be **1–5 characters**.", ERROR_RED)
        await interaction.followup.send(embed=err, ephemeral=True)
        return

    if contains_profanity(team_name):
        err = base_embed("❌ Inappropriate Name", "Please use a respectful team name.", ERROR_RED)
        await interaction.followup.send(embed=err, ephemeral=True)
        return

    # Create scrim entry
    scrim_id = str(random.randint(100000, 999999))
    active_scrims[scrim_id] = {
        'requester_id': interaction.user.id,
        'size': size,
        'code': code,
        'team_name': team_name,
        'ref_caster': ref_caster,
        'max_teams': 2,
        'accepted_teams': [],
        'message_ids': {}
    }

    # Stats
    gid = str(interaction.guild_id)
    command_usage_stats.setdefault(gid, {'find_scrim': 0, 'accepted': 0})['find_scrim'] += 1
    db['stats'] = command_usage_stats
    save_db(db)

    # Broadcast in background
    bot.loop.create_task(broadcast_scrim(scrim_id))

    ok_embed = base_embed(
        title="📡  Scrim Broadcasted!",
        description=(
            f"Your **{size}** scrim request has been sent to **{len(bot.guilds)}** server(s)!\n\n"
            f"You'll receive a DM when a team accepts. 🎮"
        ),
        color=MINT_ACCENT
    )
    ok_embed.add_field(name="🏷️ Team", value=team_name, inline=True)
    ok_embed.add_field(name="⚖️ Ref/Caster", value=ref_caster, inline=True)
    ok_embed.add_field(name="🔑 Code", value=f"||**{code}**||", inline=True)
    await interaction.followup.send(embed=ok_embed, ephemeral=True)

# ─── /settings ───────────────────────────────────────────────────────────────
@bot.tree.command(name="settings", description="⚙️ Configure bot settings for this server.")
@app_commands.describe(
    action="What to do",
    value="Value for add/remove word actions"
)
@app_commands.choices(action=[
    app_commands.Choice(name="➕ Add Banned Word",     value="add_word"),
    app_commands.Choice(name="➖ Remove Banned Word",  value="remove_word"),
    app_commands.Choice(name="👋 Toggle Welcome DMs",  value="toggle_welcome"),
    app_commands.Choice(name="📋 Show Settings",       value="show"),
])
async def settings(interaction: discord.Interaction, action: str, value: str = None):
    if not interaction.user.guild_permissions.administrator:
        err = base_embed("🚫 Permission Denied", "Only **Admins** can change settings.", ERROR_RED)
        await interaction.response.send_message(embed=err, ephemeral=True)
        return

    gid = str(interaction.guild_id)
    s = db['server_settings'].setdefault(gid, {
        'banned_words': [],
        'welcome_dm': True,
        'scrim_notifications': True
    })

    if action == "add_word":
        if not value:
            await interaction.response.send_message(
                embed=base_embed("❌ Missing Value", "Provide a word to ban using the `value` field.", ERROR_RED),
                ephemeral=True
            )
            return
        word = value.lower().strip()
        if word in s['banned_words']:
            await interaction.response.send_message(
                embed=base_embed("⚠️ Already Banned", f"`{word}` is already on the banned list.", GOLD),
                ephemeral=True
            )
            return
        s['banned_words'].append(word)
        save_db(db)
        await interaction.response.send_message(
            embed=base_embed("✅ Word Banned", f"Added `{word}` to the banned word list.", SUCCESS_GREEN),
            ephemeral=True
        )

    elif action == "remove_word":
        if not value:
            await interaction.response.send_message(
                embed=base_embed("❌ Missing Value", "Provide a word to remove using the `value` field.", ERROR_RED),
                ephemeral=True
            )
            return
        word = value.lower().strip()
        if word not in s['banned_words']:
            await interaction.response.send_message(
                embed=base_embed("⚠️ Not Found", f"`{word}` is not in the banned word list.", GOLD),
                ephemeral=True
            )
            return
        s['banned_words'].remove(word)
        save_db(db)
        await interaction.response.send_message(
            embed=base_embed("✅ Word Removed", f"Removed `{word}` from the banned word list.", SUCCESS_GREEN),
            ephemeral=True
        )

    elif action == "toggle_welcome":
        s['welcome_dm'] = not s['welcome_dm']
        save_db(db)
        state = "**ON** ✅" if s['welcome_dm'] else "**OFF** ❌"
        await interaction.response.send_message(
            embed=base_embed("👋 Welcome DMs Updated", f"Welcome DMs are now {state}.", MINT_ACCENT),
            ephemeral=True
        )

    elif action == "show":
        banned_display = (
            ", ".join(f"`{w}`" for w in s['banned_words']) if s['banned_words'] else "*None set*"
        )
        embed = base_embed(
            title=f"⚙️  Settings — {interaction.guild.name}",
            color=BLURPLE
        )
        embed.add_field(
            name="🚫 Banned Words",
            value=banned_display,
            inline=False
        )
        embed.add_field(
            name="👋 Welcome DMs",
            value="✅ ON" if s['welcome_dm'] else "❌ OFF",
            inline=True
        )
        embed.add_field(
            name="🔔 Scrim Notifications",
            value="✅ ON" if s.get('scrim_notifications', True) else "❌ OFF",
            inline=True
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    else:
        await interaction.response.send_message(
            embed=base_embed("✅ Settings Updated", "Your changes have been saved.", SUCCESS_GREEN),
            ephemeral=True
        )

# ─── Global error handler ────────────────────────────────────────────────────
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.error(f"App command error: {error}", exc_info=True)
    msg = "❌ An unexpected error occurred. Please try again."
    if isinstance(error, app_commands.MissingPermissions):
        msg = "🚫 You don't have permission to use this command."
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"⏳ Command on cooldown. Try again in {error.retry_after:.1f}s."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

# ─── Web Server (OAuth2 callback) ────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route('/health')
def health():
    return {"status": "ok", "bot": str(bot.user)}, 200

@flask_app.route('/callback')
def callback():
    code = flask_request.args.get('code')
    if not code:
        return "<h1>Error</h1><p>No code provided.</p>", 400
    try:
        res = requests.post(
            'https://discord.com/api/oauth2/token',
            data={
                'client_id':     CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'grant_type':    'authorization_code',
                'code':          code,
                'redirect_uri':  REDIRECT_URI
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10
        )
        res.raise_for_status()
        token_data = res.json()
        access_token = token_data.get('access_token')
        if not access_token:
            return "<h1>Error</h1><p>Could not obtain access token.</p>", 500

        user_res = requests.get(
            'https://discord.com/api/users/@me',
            headers={'Authorization': f"Bearer {access_token}"},
            timeout=10
        )
        user_res.raise_for_status()
        user = user_res.json()
        uid  = user.get('id')
        if not uid:
            return "<h1>Error</h1><p>Could not identify user.</p>", 500

        update_user_data(uid, verified=True, token=access_token)

        # Schedule role removal safely on the bot's event loop
        async def _remove_unverified(uid_int: int):
            for guild in bot.guilds:
                member = guild.get_member(uid_int)
                if member:
                    role = discord.utils.get(guild.roles, name="Unverified")
                    if role:
                        try:
                            await member.remove_roles(role, reason="OAuth2 verified")
                        except Exception as e:
                            log.warning(f"Could not remove Unverified role: {e}")

        asyncio.run_coroutine_threadsafe(_remove_unverified(int(uid)), bot.loop)

        # Add to target guild
        requests.put(
            f"https://discord.com/api/guilds/{TARGET_GUILD_ID}/members/{uid}",
            headers={'Authorization': f"Bot {TOKEN}"},
            json={'access_token': access_token},
            timeout=10
        )

        return (
            "<html><head><style>"
            "body{font-family:sans-serif;background:#2c2f33;color:#fff;display:flex;"
            "align-items:center;justify-content:center;height:100vh;margin:0}"
            ".card{background:#23272a;padding:40px;border-radius:12px;text-align:center;"
            "box-shadow:0 4px 24px #0008}"
            "h1{color:#40E0D0}p{color:#aaa}"
            "</style></head><body>"
            "<div class='card'>"
            "<h1>✅ Verified!</h1>"
            "<p>You have been successfully verified.<br>You can close this tab.</p>"
            "</div></body></html>"
        )
    except requests.RequestException as e:
        log.error(f"OAuth2 callback request error: {e}")
        return f"<h1>Error</h1><p>Network error: {e}</p>", 500
    except Exception as e:
        log.error(f"OAuth2 callback error: {e}", exc_info=True)
        return f"<h1>Error</h1><p>{e}</p>", 500

def run_flask():
    port = int(os.getenv('PORT', 5000))
    flask_app.run(host='0.0.0.0', port=port, use_reloader=False)

# ─── Entry Point ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if not TOKEN:
        log.critical("DISCORD_BOT_TOKEN is not set. Exiting.")
        raise SystemExit(1)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log.info("Flask web server started.")
    bot.run(TOKEN, log_handler=None)
