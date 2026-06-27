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
# Prioritize provided token from user
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
        'users': {}, # {user_id: {'verified': False, 'wins': 0, 'losses': 0, 'token': None}}
        'server_settings': {},
        'global_settings': {'banned_words': [], 'version': [0, 0, 1]},
        'stats': {}
    }

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

db = load_db()

# --- Memory (Sync with DB) --- #
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

def update_server_settings(guild_id, **kwargs):
    gid = str(guild_id)
    settings = get_server_settings(gid)
    settings.update(kwargs)
    db['server_settings'][gid] = settings
    save_db(db)

global_settings = db['global_settings']

def get_version_string():
    return f"{global_settings['version'][0]}.{global_settings['version'][1]}.{global_settings['version'][2]}"

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
    return get_version_string()

# --- Colors for Embeds (Aurora Theme) ---
BLURPLE = 0x5865F2
MINT_ACCENT = 0x40E0D0
SUCCESS_GREEN = 0x2ECC71
ERROR_RED = 0xE74C3C

# --- Profanity Filter ---
PROFANITY_LIST = [
    "slur1", "slur2", "swear1", "swear2", 
    "f*ck", "sh*t", "b*tch", "n*gger", "r*tard"
]

def contains_profanity(text):
    text = text.lower()
    for word in PROFANITY_LIST:
        if word in text:
            return True
    return False

# --- Utility Functions ---
async def send_welcome_message(user: discord.User):
    try:
        async for message in user.history(limit=20):
            if message.author == bot.user:
                await message.delete()
    except Exception as e:
        print(f"Error cleaning history for {user.name}: {e}")

    if user.id in users_who_received_requirements:
        return

    embed = discord.Embed(
        title="🦍 Gorilla Tag Scrim Finder",
        description="The ultimate tool for organizing competitive scrims across the community.",
        color=BLURPLE
    )
    
    embed.add_field(
        name="🚀 How It Works",
        value=(
            "• **`/findscrim`**: Create a request in seconds.\n"
            "• **Global Reach**: Your request hits every server instantly.\n"
            "• **Instant Match**: Teams join via the interactive broadcast.\n"
            "• **Secure**: Only authorized Admins/Owners can initiate."
        ),
        inline=False
    )
    
    embed.add_field(
        name="🔗 Expand Your Network",
        value="[Click here to add the bot to your clan!](https://discord.com/oauth2/authorize?client_id=1518171487666831452&permissions=4503602043373585&integration_type=0&scope=bot%20applications.commands%20identify%20guilds.join&redirect_uri=https%3A%2F%2Fweb-production-089e6.up.railway.app%2Fcallback&response_type=code)",
        inline=False
    )

    embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")
    
    try:
        await user.send(embed=embed)
        users_who_received_requirements.add(user.id)
    except discord.Forbidden:
        print(f"Could not send welcome message to {user.name} - DMs blocked.")

async def cleanup_dms(user: discord.User):
    try:
        async for message in user.history(limit=50):
            if message.author == bot.user:
                await message.delete()
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"Error cleaning DMs for {user.name}: {e}")

async def delete_after_delay(message: discord.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except Exception as e:
        print(f"Error deleting message: {e}")

# --- Events --- #
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s) globally.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    gid = str(message.guild.id) if message.guild else None
    local_banned = db['server_settings'].get(gid, {}).get('banned_words', []) if gid else []
    all_banned = global_settings['banned_words'] + local_banned

    if any(word.lower() in message.content.lower() for word in all_banned):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, your message contained a restricted word.", delete_after=5)
        except:
            pass

    await bot.process_commands(message)

@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Manually sync slash commands (Owner only)"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Successfully synced {len(synced)} slash commands globally!")
    except Exception as e:
        await ctx.send(f"Error syncing: {e}")

@bot.event
async def on_member_join(member):
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
        print(f"Error handling join roles in {member.guild.name}: {e}")

    if get_server_settings(gid).get('welcome_dm', True):
        await send_welcome_message(member)

# --- Modals --- #
class ClanNameModal(ui.Modal, title='🦍 Enter Your Clan Name'):
    clan_name = ui.TextInput(
        label='Clan Name (1-5 characters)',
        placeholder='e.g., ABC, FROG',
        min_length=1,
        max_length=5,
        required=True
    )

    def __init__(self, scrim_id: str):
        super().__init__()
        self.scrim_id = scrim_id

    async def on_submit(self, interaction: discord.Interaction):
        if contains_profanity(self.clan_name.value):
            await interaction.response.send_message("❌ Please use a respectful clan name.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.followup.send("❌ This scrim request is no longer active.", ephemeral=True)
            return

        if interaction.user.id == scrim_info['requester_id']:
            await interaction.followup.send("❌ You cannot join your own scrim request.", ephemeral=True)
            return

        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.followup.send("❌ This scrim is already full!", ephemeral=True)
            return

        await send_welcome_message(interaction.user)

        scrim_info['accepted_teams'].append({
            'user_id': interaction.user.id,
            'clan_name': self.clan_name.value
        })
        
        gid = str(interaction.guild_id)
        if gid not in command_usage_stats: command_usage_stats[gid] = {'find_scrim': 0, 'accepted': 0}
        command_usage_stats[gid]['accepted'] += 1
        db['stats'] = command_usage_stats
        save_db(db)

        requester = bot.get_user(scrim_info['requester_id'])
        if requester:
            dm_embed = discord.Embed(
                title=f"✅ Scrim Accepted!",
                description=f"Opponent \"**{self.clan_name.value}**\" has accepted your {scrim_info['size']} scrim!",
                color=MINT_ACCENT
            )
            dm_embed.add_field(name="🔑 Join Code:", value=f"||***{scrim_info['code']}***||", inline=False)
            dm_embed.add_field(name="👤 Who accepted:", value=f"<@{interaction.user.id}> ({self.clan_name.value})")
            dm_embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")
            try:
                dm_message = await requester.send(embed=dm_embed)
                bot.loop.create_task(delete_after_delay(dm_message, 1200))
            except discord.Forbidden:
                pass

        await self.update_scrim_message(scrim_info)
        await interaction.followup.send(f"✅ You have accepted the scrim!\n\n**Join Code:** ||***{scrim_info['code']}***||", ephemeral=True)

    async def update_scrim_message(self, scrim_info):
        for guild in bot.guilds:
            for channel_id in scrim_info['message_ids']:
                if channel_id in [c.id for c in guild.text_channels]:
                    try:
                        channel = bot.get_channel(channel_id)
                        message = await channel.fetch_message(scrim_info['message_ids'][channel_id])
                        if message:
                            embed = message.embeds[0]
                            embed.set_field_at(1, name="👥 Accepted Teams:", value=f"{len(scrim_info['accepted_teams'])}/{scrim_info['max_teams']}", inline=True)
                            if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
                                embed.color = SUCCESS_GREEN
                                await message.edit(embed=embed, view=None)
                            else:
                                await message.edit(embed=embed)
                    except: pass

# --- Views --- #
class ScrimView(ui.View):
    def __init__(self, scrim_id: str):
        super().__init__(timeout=1200)
        self.scrim_id = scrim_id

    @ui.button(label="Join Scrim", style=discord.ButtonStyle.success, emoji="🎮")
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ClanNameModal(self.scrim_id))

# --- Slash Commands --- #
@bot.tree.command(name="findscrim", description="🚀 Find a scrim!")
@app_commands.describe(size="Scrim size", ref_caster="Need ref/caster?", code="3-digit code", team_name="Your team name")
@app_commands.choices(size=[
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
])
async def find_scrim(interaction: discord.Interaction, size: str, ref_caster: str, code: str, team_name: str):
    if not interaction.user.guild_permissions.administrator and not interaction.user.id == interaction.guild.owner_id:
        if not any(role.name.lower() in ['admin', 'owner'] for role in interaction.user.roles):
            await interaction.response.send_message("❌ Only Admin/Owner can use this.", ephemeral=True)
            return

    if not (code.isdigit() and len(code) == 3):
        await interaction.response.send_message("❌ Code must be 3 digits.", ephemeral=True)
        return
    
    if contains_profanity(team_name):
        await interaction.response.send_message("❌ Respectful team names only please.", ephemeral=True)
        return

    scrim_id = str(random.randint(100000, 999999))
    active_scrims[scrim_id] = {
        'requester_id': interaction.user.id,
        'size': size,
        'code': code,
        'max_teams': 2,
        'accepted_teams': [],
        'message_ids': {}
    }

    embed = discord.Embed(title=f"🦍 Scrim Request: {size}", description=f"Requested by **{team_name}**!", color=BLURPLE)
    embed.add_field(name="👤 Requester:", value=f"<@{interaction.user.id}>", inline=True)
    embed.add_field(name="👥 Accepted Teams:", value="0/2", inline=True)
    embed.add_field(name="⚖️ Ref/Caster:", value=ref_caster, inline=False)
    embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")

    await interaction.response.send_message(f"📡 Broadcasting to {len(bot.guilds)} servers!", ephemeral=True)

    gid = str(interaction.guild_id)
    if gid not in command_usage_stats: command_usage_stats[gid] = {'find_scrim': 0, 'accepted': 0}
    command_usage_stats[gid]['find_scrim'] += 1
    db['stats'] = command_usage_stats
    save_db(db)

    for guild in bot.guilds:
        target = None
        for name in ['scrims', 'general']:
            target = discord.utils.get(guild.text_channels, name=name)
            if target: break
        if not target: target = guild.system_channel
        if not target: target = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

        if target:
            try:
                msg = await target.send(embed=embed, view=ScrimView(scrim_id))
                active_scrims[scrim_id]['message_ids'][target.id] = msg.id
            except: pass

@bot.tree.command(name="leave_server", description="🛡️ Admin: Leave a server.")
async def leave_server(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return
    
    options = [discord.SelectOption(label=g.name[:100], value=str(g.id)) for g in bot.guilds[:25]]
    if not options:
        await interaction.response.send_message("❌ No servers found.", ephemeral=True)
        return

    select = ui.Select(placeholder="Select a server to leave...", options=options)
    
    async def select_callback(inter: discord.Interaction):
        guild_id = int(select.values[0])
        guild = bot.get_guild(guild_id)
        if guild:
            await guild.leave()
            await inter.response.send_message(f"✅ Successfully left **{guild.name}**.", ephemeral=True)
        else:
            await inter.response.send_message("❌ Server not found.", ephemeral=True)

    select.callback = select_callback
    view = ui.View()
    view.add_item(select)
    await interaction.response.send_message("Choose a server to leave:", view=view, ephemeral=True)

@bot.tree.command(name="leaderboard", description="🏆 Show top servers using the bot.")
async def admin_leaderboard(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("❌ Unauthorized access.", ephemeral=True)
        return
    
    sorted_stats = sorted(command_usage_stats.items(), key=lambda x: x[1]['find_scrim'], reverse=True)[:10]
    
    description = ""
    for i, (gid, stats) in enumerate(sorted_stats, 1):
        guild = bot.get_guild(int(gid))
        name = guild.name if guild else "Unknown Server"
        description += f"**{i}. {name}**\nRequests: `{stats['find_scrim']}` | Accepts: `{stats['accepted']}`\n\n"
    
    embed = discord.Embed(title="🏆 Server Leaderboard", description=description or "No data yet.", color=MINT_ACCENT)
    embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="settings", description="⚙️ Configure bot settings for this server.")
@app_commands.describe(action="What to do", value="Value (for words) or True/False (for toggles)")
@app_commands.choices(action=[
    app_commands.Choice(name="Add Banned Word", value="add_word"),
    app_commands.Choice(name="Remove Banned Word", value="remove_word"),
    app_commands.Choice(name="Toggle Welcome DMs", value="toggle_welcome"),
    app_commands.Choice(name="Toggle Scrim Notifications", value="toggle_scrim"),
    app_commands.Choice(name="Show Settings", value="show")
])
async def settings(interaction: discord.Interaction, action: str, value: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Only administrators can change settings.", ephemeral=True)
        return

    gid = str(interaction.guild_id)
    if gid not in db['server_settings']: 
        db['server_settings'][gid] = {'banned_words': [], 'welcome_dm': True, 'scrim_notifications': True}

    if action == "add_word" and value:
        if value.lower() not in db['server_settings'][gid]['banned_words']:
            db['server_settings'][gid]['banned_words'].append(value.lower())
            save_db(db)
            await interaction.response.send_message(f"✅ Added `{value}` to banned words.", ephemeral=True)
    elif action == "remove_word" and value:
        if value.lower() in db['server_settings'][gid]['banned_words']:
            db['server_settings'][gid]['banned_words'].remove(value.lower())
            save_db(db)
            await interaction.response.send_message(f"✅ Removed `{value}` from banned words.", ephemeral=True)
    elif action == "toggle_welcome":
        current = db['server_settings'][gid].get('welcome_dm', True)
        db['server_settings'][gid]['welcome_dm'] = not current
        save_db(db)
        status = "ENABLED" if not current else "DISABLED"
        await interaction.response.send_message(f"👋 Welcome DMs are now **{status}**.", ephemeral=True)
    elif action == "toggle_scrim":
        current = db['server_settings'][gid].get('scrim_notifications', True)
        db['server_settings'][gid]['scrim_notifications'] = not current
        save_db(db)
        status = "ENABLED" if not current else "DISABLED"
        await interaction.response.send_message(f"🔔 Scrim Notifications are now **{status}**.", ephemeral=True)
    elif action == "show":
        s = db['server_settings'][gid]
        words = ", ".join(s['banned_words']) or "None"
        embed = discord.Embed(title=f"⚙️ Server Settings for {interaction.guild.name}", color=BLURPLE)
        embed.add_field(name="🚫 Banned Words", value=f"`{words}`", inline=False)
        embed.add_field(name="👋 Welcome DMs", value=f"`{'ON' if s.get('welcome_dm', True) else 'OFF'}`", inline=True)
        embed.add_field(name="🔔 Scrim Notifications", value=f"`{'ON' if s.get('scrim_notifications', True) else 'OFF'}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="update", description="📢 Global bot update and management.")
@app_commands.describe(action="Global action to perform", value="Update notes or value")
@app_commands.choices(action=[
    app_commands.Choice(name="Push Version Update", value="push_update"),
    app_commands.Choice(name="Global Add Banned Word", value="g_add"),
    app_commands.Choice(name="Global Remove Banned Word", value="g_remove"),
    app_commands.Choice(name="Force Global Sync", value="sync_all")
])
async def global_update(interaction: discord.Interaction, action: str, value: str = None):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return

    if action == "push_update":
        new_version = increment_version()
        await interaction.response.send_message(f"🚀 Pushing Update v{new_version} to all users...", ephemeral=True)
        
        update_embed = discord.Embed(
            title=f"📢 Bot Updated to v{new_version}",
            description=value or f"The bot has been updated to the latest version. Please use `/findscrim` to see the new features!",
            color=MINT_ACCENT
        )
        update_embed.add_field(name="Current Version", value=f"`{new_version}`", inline=True)
        update_embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")

        success_count = 0
        for uid in list(users_who_received_requirements):
            user = bot.get_user(uid)
            if user:
                try:
                    await user.send(embed=update_embed)
                    success_count += 1
                except: pass
        
        await bot.tree.sync()
        await interaction.followup.send(f"✅ Update notification sent to {success_count} users and commands synced.", ephemeral=True)

    elif action == "g_add" and value:
        if value.lower() not in global_settings['banned_words']:
            global_settings['banned_words'].append(value.lower())
            save_db(db)
            await interaction.response.send_message(f"✅ GLOBAL: Added `{value}` to banned words.", ephemeral=True)
    elif action == "g_remove" and value:
        if value.lower() in global_settings['banned_words']:
            global_settings['g_banned_words'].remove(value.lower())
            save_db(db)
            await interaction.response.send_message(f"✅ GLOBAL: Removed `{value}` from banned words.", ephemeral=True)
    elif action == "sync_all":
        await interaction.response.defer(ephemeral=True)
        synced = await bot.tree.sync()
        await interaction.followup.send(f"✅ Global sync complete. {len(synced)} commands updated across all servers.", ephemeral=True)

# --- Web Server for OAuth2 --- #
app = Flask(__name__)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "Error: No code provided", 400

    try:
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        
        response = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
        if response.status_code != 200:
            return f"Error exchanging code: {response.text}", 400
        
        token_data = response.json()
        access_token = token_data.get('access_token')
        if not access_token:
            return "Error: No access token in response", 400

        user_response = requests.get('https://discord.com/api/users/@me', headers={
            'Authorization': f"Bearer {access_token}"
        })
        user_info = user_response.json()
        user_id = user_info.get('id')
        if not user_id:
            return "Error: Could not fetch user ID", 400

        update_user_data(user_id, verified=True, token=access_token)

        # Remove unverified role
        for guild in bot.guilds:
            member = guild.get_member(int(user_id))
            if member:
                role = discord.utils.get(guild.roles, name="Unverified")
                if role:
                    asyncio.run_coroutine_threadsafe(member.remove_roles(role), bot.loop)

        # Add user to the target server
        requests.put(
            f"https://discord.com/api/guilds/{TARGET_GUILD_ID}/members/{user_id}",
            headers={'Authorization': f"Bot {TOKEN}"},
            json={'access_token': access_token}
        )

        return "<h1>Success!</h1><p>You have been verified and added to the server. You can now close this window.</p>"
    except Exception as e:
        return f"<h1>Internal Error</h1><p>{str(e)}</p>", 500

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

# --- Run Bot and Web Server --- #
if TOKEN:
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
else:
    print("No DISCORD_BOT_TOKEN found.")
