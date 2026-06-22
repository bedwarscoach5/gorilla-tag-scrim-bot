# Gorilla Tag Scrim Finder Discord Bot

This bot helps Gorilla Tag server owners find scrims (2v2, 3v3, 4v4) for their teams. It supports slash commands, broadcasts scrim requests across multiple servers, and notifies users via DMs when their scrims are accepted.

## Features

-   **Slash Commands**: Easy-to-use `/findscrim` command.
-   **Scrim Sizes**: Supports 2v2, 3v3, and 4v4 scrims.
-   **Ref/Caster Support**: Option to request a ref or caster.
-   **Team Names**: Users can specify their clan name (1-5 characters) when joining a scrim.
-   **Broadcast System**: Scrim requests are broadcasted to designated channels (`#scrims`, `#general`, or system channel) in all servers the bot is in.
-   **DM Notifications**: Requesters are notified via DM when their scrim is accepted, including the opponent's clan name and the scrim code.
-   **Auto-Deleting DMs**: Bot DMs are automatically deleted after 20 minutes to keep inboxes clean.
-   **Railway Deployment**: Optimized for 24/7 hosting on Railway.
-   **Aurora Aesthetic**: The bot uses a Blurple and Mint color scheme for embeds, with placeholders for custom Aurora-themed images.

## Setup Instructions

Follow these steps to get your Discord bot up and running.

### 1. Create Your Discord Bot Application

1.  Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2.  Click on **"New Application"**.
3.  Give your application a name (e.g., "Gorilla Tag Scrim Finder") and click **"Create"**.
4.  Navigate to the **"Bot"** tab on the left sidebar.
5.  Click **"Add Bot"** and confirm.
6.  Under **"Privileged Gateway Intents"**, enable the following:
    -   `PRESENCE INTENT` (Optional, for bot status)
    -   `SERVER MEMBERS INTENT` (Required for guild-related features)
    -   `MESSAGE CONTENT INTENT` (Crucial for bot functionality)
7.  Make sure **"Public Bot"** is toggled **ON**.
8.  Click **"Save Changes"**.
9.  Copy your **"TOKEN"** (click "Reset Token" if you haven't already, then copy). **Keep this token secret!** You will need it for Railway deployment.

### 2. Configure OAuth2 for Invitation

1.  Navigate to the **"OAuth2"** tab on the left sidebar, then select **"URL Generator"**.
2.  Under **"Scopes"**, check the following:
    -   `bot`
    -   `applications.commands`
3.  Under **"Bot Permissions"**, check these boxes:
    -   `Send Messages`
    -   `Embed Links`
    -   `Read Message History`
    -   `Use Slash Commands`
4.  At the bottom, ensure **"Integration Type"** is set to **"Guild Install"**.
5.  Copy the **"Generated URL"**. This is your bot's invite link.

### 3. Invite the Bot to Your Server

1.  Paste the **Generated URL** (from step 2.5) into your web browser.
2.  Select the server you want to add the bot to and click **"Authorize"**.

### 4. Deploy to Railway

Railway is a platform that allows you to host your bot 24/7.

1.  **Create a GitHub Repository**: Create a new public or private repository on GitHub (e.g., `gorilla-tag-scrim-bot`).
2.  **Upload Files**: Upload all the files from this project (`bot.py`, `requirements.txt`, `Procfile`, `.env.example`, `README.md`) to your new GitHub repository.
3.  **Connect to Railway**: 
    - Go to [Railway.app](https://railway.app/) and log in with your GitHub account.
    - Click **"New Project"** -> **"Deploy from GitHub repo"**.
    - Select the GitHub repository you just created (`gorilla-tag-scrim-bot`).
4.  **Set Environment Variables**: 
    - Once the project is created on Railway, go to the **"Variables"** tab.
    - Add a new variable named `DISCORD_BOT_TOKEN` and paste your Discord bot token (copied in step 1.9) as its value.
    - Add another variable named `BOT_OWNER_ID`. Set its value to your Discord User ID. (To find your User ID: Enable Developer Mode in Discord settings, right-click your profile, and select "Copy ID").
5.  Railway will automatically deploy your bot. You can check the **"Logs"** tab in Railway to monitor its status.

## Usage

Once the bot is online in your Discord server:

-   **`/findscrim [size] [ref_caster] [code] [team_name]`**: Use this slash command in any channel the bot has access to. 
    -   `size`: Choose 2v2, 3v3, or 4v4.
    -   `ref_caster`: Specify if you need a ref or caster.
    -   `code`: A 3-digit number for the scrim code (e.g., `123`). The bot will format it as `scrim123`.
    -   `team_name`: Your team's name (1-5 characters).
-   **Joining a Scrim**: When a scrim request is broadcasted, other users can click the **"Join Scrim"** button. A modal will pop up asking for their clan name.

## Important Notes

-   **Admin/Owner Role**: Only users with an "Admin" or "Owner" role (or the server owner) can use the `/findscrim` command.
-   **Image Placeholders**: The bot's embeds use placeholder URLs for an Aurora-themed banner and thumbnail. You will need to replace these in `bot.py` with your own image URLs (e.g., from Imgur) to fully customize the visual aesthetic.
    -   `embed.set_image(url="https://i.imgur.com/your_aurora_banner.gif")`
    -   `embed.set_thumbnail(url="https://i.imgur.com/your_aurora_thumbnail.png")`

## Policy Documents

For Discord bot verification, you will need a Privacy Policy and Terms of Service. Here are the public URLs:

-   **Privacy Policy URL**: https://files.manuscdn.com/user_upload_by_module/session_file/310519663641762710/PSTQuWByAtjHQHFa.md
-   **Terms of Service URL**: https://files.manuscdn.com/user_upload_by_module/session_file/310519663641762710/WmQYpZGphbpURRpu.md

Copy and paste these links into the respective fields in your bot's settings on the Discord Developer Portal.

## Troubleshooting

If you encounter issues, check the following:

-   **Railway Logs**: Check the "Logs" tab in your Railway project for any error messages.
-   **Discord Developer Portal**: Double-check all intents, scopes, and permissions as described in the setup steps.
-   **Environment Variables**: Ensure `DISCORD_BOT_TOKEN` and `BOT_OWNER_ID` are correctly set in Railway.

---

created by frog360 and powered by Aurorasystem
