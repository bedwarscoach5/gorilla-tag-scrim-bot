
import os
import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import random
import re
import requests
from flask import Flask, request

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

active_scrims = {}
users_who_received_requirements = set()
command_usage_stats = {} # {guild_id: {'find_scrim': 0, 'accepted': 0}}
authorized_users = [836166145387397120] # Strictly restricted to this specific user ID
server_settings = {} # {guild_id: {'banned_words': [], 'welcome_dm': True, 'scrim_notifications': True}}
global_settings = {
    'banned_words': [],
    'version': [0, 0, 1] # [Major, Minor, Patch]
}

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
    return get_version_string()

# --- Colors for Embeds (Aurora Theme) ---
BLURPLE = 0x5865F2
MINT_ACCENT = 0x40E0D0

# --- Profanity Filter ---
# Basic list of common slurs/swear words. For a production bot, a more comprehensive library is recommended.
PROFANITY_LIST = [
    "slur1", "slur2", "swear1", "swear2", # Placeholders - user can expand this list
    "f*ck", "sh*t", "b*tch", "n*gger", "r*tard" # Examples with masking for safety in code
]

def contains_profanity(text):
    text = text.lower()
    for word in PROFANITY_LIST:
        if word in text:
            return True
    return False

# --- Utility Functions ---
async def send_welcome_message(user: discord.User):
    # First, clean up any previous messages from the bot to this user
    try:
        async for message in user.history(limit=20):
            if message.author == bot.user:
                await message.delete()
    except Exception as e:
        print(f"Error cleaning history for {user.name}: {e}")

    if user.id in users_who_received_requirements:
        return

    # ANSI colored separators for a clean aesthetic
    mint_line = "```ansi\n\u001b[1;36m▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\u001b[0m\n```"
    blurple_line = "```ansi\n\u001b[1;34m▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\u001b[0m\n```"

    embed = discord.Embed(
        title="🦍 Gorilla Tag Scrim Finder",
        description="The ultimate tool for organizing competitive scrims across the community.",
        color=BLURPLE
    )
    
    embed.add_field(
        name="🚀 How It Works",
        value=f"{mint_line}• **`/findscrim`**: Create a request in seconds.\n• **Global Reach**: Your request hits every server instantly.\n• **Instant Match**: Teams join via the interactive broadcast.\n• **Secure**: Only authorized Admins/Owners can initiate.{blurple_line}",
        inline=False
    )
    
    embed.add_field(
        name="🔗 Expand Your Network",
        value=f"{mint_line}[Click here to add the bot to your clan!](https://discord.com/oauth2/authorize?client_id=1518171487666831452&permissions=4503602043373585&integration_type=0&scope=bot){blurple_line}",
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

    # Check for banned words (Local and Global)
    gid = str(message.guild.id) if message.guild else None
    local_banned = server_settings.get(gid, {}).get('banned_words', []) if gid else []
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
    if server_settings.get(gid, {}).get('welcome_dm', True):
        await send_welcome_message(member)

# --- Modals --- #
class ClanNameModal(ui.Modal, title='Enter Your Clan Name'):
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
        # Profanity check
        if contains_profanity(self.clan_name.value):
            await interaction.response.send_message("Please use a respectful clan name. No slurs or swear words allowed.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.followup.send("This scrim request is no longer active.", ephemeral=True)
            return

        if interaction.user.id == scrim_info['requester_id']:
            await interaction.followup.send("You cannot join your own scrim request.", ephemeral=True)
            return

        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.followup.send("This scrim is already full!", ephemeral=True)
            return

        # Check if user has received requirements before proceeding
        await send_welcome_message(interaction.user)

        scrim_info['accepted_teams'].append({
            'user_id': interaction.user.id,
            'clan_name': self.clan_name.value
        })
        
        # Track stats
        gid = str(interaction.guild_id)
        if gid not in command_usage_stats: command_usage_stats[gid] = {'find_scrim': 0, 'accepted': 0}
        command_usage_stats[gid]['accepted'] += 1

        requester = bot.get_user(scrim_info['requester_id'])
        if requester:
            dm_embed = discord.Embed(
                title=f"Scrim Accepted!",
                description=f"Opponent \"**{self.clan_name.value}**\" has accepted your {scrim_info['size']} scrim!",
                color=MINT_ACCENT
            )
            dm_embed.add_field(name="Join Code:", value=f"||***{scrim_info['code']}***||", inline=False)
            dm_embed.add_field(name="Who accepted:", value=f"<@{interaction.user.id}> ({self.clan_name.value})")
            dm_embed.set_footer(text="created by frog360 and powered by Aurorasystem")
            try:
                dm_message = await requester.send(embed=dm_embed)
                bot.loop.create_task(delete_after_delay(dm_message, 1200)) # 20 mins
            except discord.Forbidden:
                pass

        await self.update_scrim_message(scrim_info)
        await interaction.followup.send(f"You have accepted the scrim! Requester has been notified.\n\n**Join Code:** ||***{scrim_info['code']}***||", ephemeral=True)

    async def update_scrim_message(self, scrim_info):
        channel = bot.get_channel(scrim_info['channel_id'])
        if not channel: return
        try:
            message = await channel.fetch_message(scrim_info['message_id'])
            if message:
                embed = message.embeds[0]
                embed.set_field_at(1, name="Accepted Teams:", value=f"{len(scrim_info['accepted_teams'])}/{scrim_info['max_teams']}", inline=True)
                await message.edit(embed=embed)
        except: pass

# --- Views --- #
class ScrimView(ui.View):
    def __init__(self, scrim_id: str):
        super().__init__(timeout=1200) # 20 minutes timeout
        self.scrim_id = scrim_id

    @ui.button(label="Join Scrim", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ClanNameModal(self.scrim_id))

# --- Slash Commands --- #
@bot.tree.command(name="findscrim", description="Find a scrim!")
@app_commands.describe(size="Scrim size", ref_caster="Need ref/caster?", code="3-digit code", team_name="Your team name")
@app_commands.choices(size=[
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
])
async def find_scrim(interaction: discord.Interaction, size: str, ref_caster: str, code: str, team_name: str):
    # Role check
    if not interaction.user.guild_permissions.administrator and not interaction.user.id == interaction.guild.owner_id:
        if not any(role.name.lower() in ['admin', 'owner'] for role in interaction.user.roles):
            await interaction.response.send_message("Only Admin/Owner can use this.", ephemeral=True)
            return

    if not (code.isdigit() and len(code) == 3):
        await interaction.response.send_message("Code must be 3 digits.", ephemeral=True)
        return
    
    if contains_profanity(team_name):
        await interaction.response.send_message("Respectful team names only please.", ephemeral=True)
        return

    scrim_id = str(random.randint(100000, 999999))
    embed = discord.Embed(title=f"Scrim Request: {size}", description=f"Requested by **{team_name}**!", color=BLURPLE)
    embed.add_field(name="Requester:", value=f"<@{interaction.user.id}>", inline=True)
    embed.add_field(name="Accepted Teams:", value="0/2", inline=True)
    embed.add_field(name="Ref/Caster:", value=ref_caster, inline=False)
    embed.set_footer(text="created by frog360 and powered by Aurorasystem")
    embed.set_image(url="https://i.imgur.com/your_aurora_banner.gif")

    await interaction.response.send_message(f"Broadcasting to {len(bot.guilds)} servers!", ephemeral=True)

    # Track stats
    gid = str(interaction.guild_id)
    if gid not in command_usage_stats: command_usage_stats[gid] = {'find_scrim': 0, 'accepted': 0}
    command_usage_stats[gid]['find_scrim'] += 1

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
                active_scrims[scrim_id] = {
                    'requester_id': interaction.user.id, 'channel_id': msg.channel.id, 'message_id': msg.id,
                    'size': size, 'code': f"scrim{code}", 'max_teams': 2, 'accepted_teams': []
                }
                bot.loop.create_task(delete_after_delay(msg, 1200))
            except: pass

# --- Advanced Admin Commands --- #
@bot.tree.command(name="join", description="Force join accepted users to the current server.")
async def admin_join(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("Unauthorized access.", ephemeral=True)
        return
    
    await interaction.response.send_message("Attempting to sync users to this server...", ephemeral=True)
    # Note: This requires the 'guilds.join' scope and for users to have authorized the bot.
    # Without specific OAuth2 flow for each user, the bot cannot force-join them.
    # This command serves as a placeholder for that logic.
    await interaction.followup.send("Feature requires individual user OAuth2 authorization (guilds.join scope).", ephemeral=True)

@bot.tree.command(name="count", description="Show bot statistics.")
async def admin_count(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("Unauthorized access.", ephemeral=True)
        return
    
    total_users = sum(len(g.members) for g in bot.guilds)
    embed = discord.Embed(title="📊 Bot Statistics", color=BLURPLE)
    embed.add_field(name="Servers", value=f"```{len(bot.guilds)}```", inline=True)
    embed.add_field(name="Total Users", value=f"```{total_users}```", inline=True)
    embed.add_field(name="Active Scrims", value=f"```{len(active_scrims)}```", inline=True)
    embed.set_footer(text="Created by frog360 • Powered by Aurorasystem")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ban", description="Remove the bot from a specific server.")
async def admin_ban(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("Unauthorized access.", ephemeral=True)
        return
    
    options = [discord.SelectOption(label=g.name[:100], value=str(g.id)) for g in bot.guilds[:25]]
    if not options:
        await interaction.response.send_message("No servers found.", ephemeral=True)
        return

    select = ui.Select(placeholder="Select a server to leave...", options=options)
    
    async def select_callback(inter: discord.Interaction):
        guild_id = int(select.values[0])
        guild = bot.get_guild(guild_id)
        if guild:
            await guild.leave()
            await inter.response.send_message(f"Successfully left **{guild.name}**.", ephemeral=True)
        else:
            await inter.response.send_message("Server not found.", ephemeral=True)

    select.callback = select_callback
    view = ui.View()
    view.add_item(select)
    await interaction.response.send_message("Choose a server to ban the bot from:", view=view, ephemeral=True)

@bot.tree.command(name="leaderboard", description="Show top servers using the bot.")
async def admin_leaderboard(interaction: discord.Interaction):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("Unauthorized access.", ephemeral=True)
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

@bot.tree.command(name="settings", description="Configure bot settings for this server.")
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
        await interaction.response.send_message("Only administrators can change settings.", ephemeral=True)
        return

    gid = str(interaction.guild_id)
    if gid not in server_settings: 
        server_settings[gid] = {'banned_words': [], 'welcome_dm': True, 'scrim_notifications': True}

    if action == "add_word" and value:
        if value.lower() not in server_settings[gid]['banned_words']:
            server_settings[gid]['banned_words'].append(value.lower())
            await interaction.response.send_message(f"✅ Added `{value}` to banned words.", ephemeral=True)
    elif action == "remove_word" and value:
        if value.lower() in server_settings[gid]['banned_words']:
            server_settings[gid]['banned_words'].remove(value.lower())
            await interaction.response.send_message(f"✅ Removed `{value}` from banned words.", ephemeral=True)
    elif action == "toggle_welcome":
        current = server_settings[gid].get('welcome_dm', True)
        server_settings[gid]['welcome_dm'] = not current
        status = "ENABLED" if not current else "DISABLED"
        await interaction.response.send_message(f"👋 Welcome DMs are now **{status}**.", ephemeral=True)
    elif action == "toggle_scrim":
        current = server_settings[gid].get('scrim_notifications', True)
        server_settings[gid]['scrim_notifications'] = not current
        status = "ENABLED" if not current else "DISABLED"
        await interaction.response.send_message(f"🔔 Scrim Notifications are now **{status}**.", ephemeral=True)
    elif action == "show":
        s = server_settings[gid]
        words = ", ".join(s['banned_words']) or "None"
        msg = f"**⚙️ Server Settings for {interaction.guild.name}**\n"
        msg += f"• Banned Words: `{words}`\n"
        msg += f"• Welcome DMs: `{'ON' if s.get('welcome_dm', True) else 'OFF'}`\n"
        msg += f"• Scrim Notifications: `{'ON' if s.get('scrim_notifications', True) else 'OFF'}`"
        await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="update", description="Global bot update and management.")
@app_commands.describe(action="Global action to perform", value="Update notes or value")
@app_commands.choices(action=[
    app_commands.Choice(name="Push Version Update", value="push_update"),
    app_commands.Choice(name="Global Add Banned Word", value="g_add"),
    app_commands.Choice(name="Global Remove Banned Word", value="g_remove"),
    app_commands.Choice(name="Force Global Sync", value="sync_all")
])
async def global_update(interaction: discord.Interaction, action: str, value: str = None):
    if interaction.user.id not in authorized_users:
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
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

        # Notify all users who have received requirements (active users)
        success_count = 0
        for uid in list(users_who_received_requirements):
            user = bot.get_user(uid)
            if user:
                try:
                    await user.send(embed=update_embed)
                    success_count += 1
                except: pass
        
        # Force a sync for the current instance as part of the update
        await bot.tree.sync()
        
        await interaction.followup.send(f"✅ Update notification sent to {success_count} users and commands synced.", ephemeral=True)

    elif action == "g_add" and value:
        if value.lower() not in global_settings['banned_words']:
            global_settings['banned_words'].append(value.lower())
            await interaction.response.send_message(f"GLOBAL: Added `{value}` to banned words.", ephemeral=True)
    elif action == "g_remove" and value:
        if value.lower() in global_settings['banned_words']:
            global_settings['banned_words'].remove(value.lower())
            await interaction.response.send_message(f"GLOBAL: Removed `{value}` from banned words.", ephemeral=True)
    elif action == "sync_all":
        await interaction.response.defer(ephemeral=True)
        synced = await bot.tree.sync()
        await interaction.followup.send(f"Global sync complete. {len(synced)} commands updated across all servers.", ephemeral=True)

# --- Web Server for OAuth2 --- #
app = Flask(__name__)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "Error: No code provided", 400

    # Exchange code for access token
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
            return f"Error exchanging code: {response.text} (Check if CLIENT_SECRET and REDIRECT_URI match exactly in Discord and Railway)", 400
        
        token_data = response.json()
        access_token = token_data.get('access_token')
        if not access_token:
            return "Error: No access token in response", 400

        # Get user info to identify them
        user_response = requests.get('https://discord.com/api/users/@me', headers={
            'Authorization': f"Bearer {access_token}"
        })
        user_info = user_response.json()
        user_id = user_info.get('id')
        if not user_id:
            return "Error: Could not fetch user ID", 400

        # Add user to the target server
        add_response = requests.put(
            f"https://discord.com/api/guilds/{TARGET_GUILD_ID}/members/{user_id}",
            headers={'Authorization': f"Bot {TOKEN}"},
            json={'access_token': access_token}
        )

        if add_response.status_code in [201, 204]:
            return "<h1>Success!</h1><p>You have been added to the server. You can now close this window.</p>"
        else:
            return f"<h1>Notice</h1><p>You might already be in the server, or there was a minor issue: {add_response.text}</p>", 200
    except Exception as e:
        return f"<h1>Internal Error</h1><p>{str(e)}</p>", 500

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

# --- Run Bot and Web Server --- #
if TOKEN:
    # Run Flask in a separate thread
    import threading
    threading.Thread(target=run_flask, daemon=True).start()
    
    bot.run(TOKEN)
else:
    print("No DISCORD_BOT_TOKEN found.")
