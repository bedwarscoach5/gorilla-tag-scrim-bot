
import os
import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import random
import datetime

# --- Configuration --- #
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
BOT_OWNER_ID = int(os.getenv('BOT_OWNER_ID', 0)) # Optional, for owner-specific features

# --- Bot Setup --- #
intents = discord.Intents.default()
intents.message_content = True  # Crucial for reading message content
intents.members = True          # Required for guild-related features (e.g., checking roles)
intents.presences = True        # Optional, if you want the bot to display its status

bot = commands.Bot(command_prefix='!', intents=intents)

active_scrims = {}

# --- Colors for Embeds (Aurora Theme) ---
BLURPLE = 0x5865F2
MINT_ACCENT = 0x40E0D0

# --- Utility Functions ---
async def send_welcome_message(user: discord.User):
    embed = discord.Embed(
        title="Welcome to the Gorilla Tag Scrim Finder!",
        description="I'm here to help you find scrims quickly and efficiently.",
        color=BLURPLE
    )
    embed.add_field(name="How to use me:", value="""
    - Use `/findscrim` to initiate a scrim request.
    - I will broadcast your request to all servers I'm in.
    - Teams can then accept your scrim request.
    - Only users with 'Admin' or 'Owner' roles (or server owner) can use `/findscrim`.
    """, inline=False)
    embed.add_field(name="Important:", value="""
    - Make sure to set up your Discord Developer Portal settings correctly (Intents, Scopes, Permissions).
    - Ensure your `DISCORD_BOT_TOKEN` and `BOT_OWNER_ID` are set in Railway environment variables.
    """, inline=False)
    embed.set_footer(text="created by frog360 and powered by Aurorasystem")
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        print(f"Could not send welcome message to {user.name} - DMs blocked.")

async def cleanup_dms(user: discord.User):
    try:
        async for message in user.history(limit=50):
            if message.author == bot.user:
                await message.delete()
        print(f"Cleaned DMs for {user.name}")
    except discord.Forbidden:
        print(f"Could not clean DMs for {user.name} - DMs blocked.")
    except Exception as e:
        print(f"Error cleaning DMs for {user.name}: {e}")

# --- Events --- #
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    await bot.tree.sync()
    print('Slash commands synced.')

    # Optimized DM cleanup for owner on startup
    if BOT_OWNER_ID != 0:
        owner = bot.get_user(BOT_OWNER_ID)
        if owner:
            await cleanup_dms(owner)
            await send_welcome_message(owner)

@bot.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} ({guild.id})")
    # Optionally send a welcome message to a default channel in the guild

# --- Modals --- #
class ClanNameModal(ui.Modal, title='Enter Your Clan Name'):
    clan_name = ui.TextInput(
        label='Clan Name (1-5 characters)',
        placeholder='e.g., ABC, FROG, TEAMX',
        min_length=1,
        max_length=5,
        required=True
    )

    def __init__(self, scrim_id: str, interaction: discord.Interaction):
        super().__init__()
        self.scrim_id = scrim_id
        self.original_interaction = interaction

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Defer the interaction immediately

        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.followup.send("This scrim request is no longer active.", ephemeral=True)
            return

        if interaction.user.id in [s['user_id'] for s in scrim_info['accepted_teams']]:
            await interaction.followup.send("You have already accepted this scrim.", ephemeral=True)
            return

        # Check if scrim is full
        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.followup.send("This scrim is already full!", ephemeral=True)
            return

        scrim_info['accepted_teams'].append({
            'user_id': interaction.user.id,
            'clan_name': self.clan_name.value,
            'guild_id': interaction.guild_id
        })

        requester = bot.get_user(scrim_info['requester_id'])
        if requester:
            # Notify requester in DM
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
                # Schedule DM deletion
                bot.loop.create_task(delete_dm_after_delay(dm_message, 1200)) # 20 minutes
            except discord.Forbidden:
                print(f"Could not DM requester {requester.name} - DMs blocked.")

        # Update the original scrim message with new accepted count
        await self.update_scrim_message(scrim_info)

        await interaction.followup.send(f"You have accepted the scrim with clan name **{self.clan_name.value}**! The requester has been notified.", ephemeral=True)

    async def update_scrim_message(self, scrim_info):
        channel = bot.get_channel(scrim_info['channel_id'])
        if not channel:
            return
        try:
            message = await channel.fetch_message(scrim_info['message_id'])
            if message:
                embed = message.embeds[0]
                embed.set_field_at(
                    index=1, # Assuming 'Accepted Teams' is the second field
                    name="Accepted Teams:",
                    value=f"{len(scrim_info['accepted_teams'])}/{scrim_info['max_teams']}",
                    inline=True
                )
                await message.edit(embed=embed)
        except discord.NotFound:
            print(f"Original scrim message {scrim_info['message_id']} not found.")
        except Exception as e:
            print(f"Error updating scrim message: {e}")

# --- Views (Buttons) --- #
class ScrimView(ui.View):
    def __init__(self, scrim_id: str, timeout=1800): # 30 minutes timeout
        super().__init__(timeout=timeout)
        self.scrim_id = scrim_id

    @ui.button(label="Join Scrim", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: ui.Button):
        scrim_info = active_scrims.get(self.scrim_id)
        if not scrim_info:
            await interaction.response.send_message("This scrim request is no longer active.", ephemeral=True)
            self.stop()
            return

        # Check if the user is the requester
        if interaction.user.id == scrim_info['requester_id']:
            await interaction.response.send_message("You cannot join your own scrim request.", ephemeral=True)
            return

        # Check if scrim is full
        if len(scrim_info['accepted_teams']) >= scrim_info['max_teams']:
            await interaction.response.send_message("This scrim is already full!", ephemeral=True)
            return

        await interaction.response.send_modal(ClanNameModal(self.scrim_id, interaction))

    async def on_timeout(self):
        scrim_info = active_scrims.pop(self.scrim_id, None)
        if scrim_info:
            channel = bot.get_channel(scrim_info['channel_id'])
            if channel:
                try:
                    message = await channel.fetch_message(scrim_info['message_id'])
                    if message:
                        embed = message.embeds[0]
                        embed.set_footer(text="Scrim request timed out.")
                        for item in self.children:
                            item.disabled = True
                        await message.edit(embed=embed, view=self)
                except discord.NotFound:
                    pass
        print(f"Scrim {self.scrim_id} timed out.")

# --- Slash Commands --- #
@bot.tree.command(name="findscrim", description="Find a scrim for your team!")
@app_commands.describe(
    size="The size of the scrim (e.g., 2v2, 3v3, 4v4)",
    ref_caster="Do you need a ref or caster?",
    code="A 3-digit code for the scrim (e.g., 123)",
    team_name="Your team's name (1-5 characters)"
)
@app_commands.choices(size=[
    app_commands.Choice(name="2v2", value="2v2"),
    app_commands.Choice(name="3v3", value="3v3"),
    app_commands.Choice(name="4v4", value="4v4"),
])
@app_commands.default_permissions(manage_guild=True) # Only users with manage_guild can use this by default
async def find_scrim(interaction: discord.Interaction, size: str, ref_caster: str, code: str, team_name: str):
    # Role check: Only Admin/Owner roles or server owner can use this command
    if not interaction.user.guild_permissions.administrator and not interaction.user.id == interaction.guild.owner_id:
        has_allowed_role = False
        for role in interaction.user.roles:
            if role.name.lower() in ['admin', 'owner']:
                has_allowed_role = True
                break
        if not has_allowed_role:
            await interaction.response.send_message("You need to have an 'Admin' or 'Owner' role, or be the server owner to use this command.", ephemeral=True)
            return

    if not (code.isdigit() and len(code) == 3):
        await interaction.response.send_message("The scrim code must be a 3-digit number.", ephemeral=True)
        return

    if not (1 <= len(team_name) <= 5):
        await interaction.response.send_message("Your team name must be between 1 and 5 characters.", ephemeral=True)
        return

    scrim_code = f"scrim{code}"
    max_teams = 2 # Always 2 teams for a scrim

    scrim_id = str(random.randint(100000, 999999)) # Unique ID for this scrim request

    embed = discord.Embed(
        title=f"Scrim Request: {size}",
        description=f"A {size} scrim has been requested by **{team_name}**!",
        color=BLURPLE
    )
    embed.add_field(name="Requester:", value=f"<@{interaction.user.id}> ({team_name})", inline=True)
    embed.add_field(name="Accepted Teams:", value=f"0/{max_teams}", inline=True)
    embed.add_field(name="Ref/Caster Needed:", value=ref_caster, inline=False)
    embed.set_footer(text="created by frog360 and powered by Aurorasystem")
    # Placeholder for Aurora themed image/gif
    embed.set_image(url="https://i.imgur.com/your_aurora_banner.gif") # User to replace
    embed.set_thumbnail(url="https://i.imgur.com/your_aurora_thumbnail.png") # User to replace

    view = ScrimView(scrim_id)

    await interaction.response.send_message(f"Your scrim request has been submitted to {len(bot.guilds)} servers!", ephemeral=True)

    # Broadcast to all servers
    broadcast_count = 0
    for guild in bot.guilds:
        target_channel = None
        # Prioritize #scrims, then #general, then system channel, then any text channel
        for channel in guild.text_channels:
            if channel.name == 'scrims':
                target_channel = channel
                break
            if channel.name == 'general':
                target_channel = channel
        if not target_channel and guild.system_channel:
            target_channel = guild.system_channel
        if not target_channel:
            target_channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

        if target_channel:
            try:
                message = await target_channel.send(embed=embed, view=view)
                active_scrims[scrim_id] = {
                    'requester_id': interaction.user.id,
                    'channel_id': message.channel.id,
                    'message_id': message.id,
                    'size': size,
                    'ref_caster': ref_caster,
                    'code': scrim_code,
                    'max_teams': max_teams,
                    'accepted_teams': [],
                    'team_name': team_name
                }
                broadcast_count += 1
            except discord.Forbidden:
                print(f"Could not send scrim request to {guild.name} - missing permissions.")
            except Exception as e:
                print(f"Error sending scrim request to {guild.name}: {e}")

    # Update the ephemeral message with actual broadcast count
    await interaction.followup.send(f"Successfully broadcasted your scrim request to {broadcast_count} servers!", ephemeral=True)

    # Placeholder for estimated chance of scrimming (complex logic, needs more data/roles)
    # For now, a simple message
    await interaction.followup.send("Current estimated chance of scrimming: Calculating based on server activity...", ephemeral=True)

async def delete_dm_after_delay(message: discord.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except discord.NotFound:
        pass # Message already deleted
    except Exception as e:
        print(f"Error deleting DM: {e}")

# --- Run Bot --- #
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_BOT_TOKEN not found in environment variables.")
    print("Please set the DISCORD_BOT_TOKEN environment variable.")
