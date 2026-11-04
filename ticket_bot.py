import discord
from discord import app_commands
import os
import asyncio
import time
from aiohttp import web
from dotenv import load_dotenv

# Load token securely from Railway Environment Variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

STAFF_ROLE_NAME = "Staff"
TICKETS_CATEGORY_NAME = "Tickets"
AUTO_CLOSE_SECONDS = 86400  # 1 day = 24 hours
PORT = int(os.environ.get("PORT", 8080))

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

async def get_or_create_tickets_category(guild):
    for cat in guild.categories:
        if cat.name == TICKETS_CATEGORY_NAME:
            return cat
    return await guild.create_category(TICKETS_CATEGORY_NAME, reason="Ticket system")

def get_staff_role(guild):
    return discord.utils.get(guild.roles, name=STAFF_ROLE_NAME)

# ─── VIEWS ──────────────────────────────────────────────────────────

class TicketActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        guild = interaction.guild
        staff = get_staff_role(guild)
        is_staff = staff in interaction.user.roles if staff else False
        is_owner = channel.topic and f"ticket-owner:{interaction.user.id}" in channel.topic
        
        if not (is_staff or is_owner):
            return await interaction.response.send_message("Only the ticket opener or staff can close this.", ephemeral=True)

        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        await asyncio.sleep(2)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception as e:
            print(f"[!] close delete failed: {e}")

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="claim_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        staff = get_staff_role(guild)
        is_staff = staff in interaction.user.roles if staff else False
        
        if not is_staff:
            return await interaction.response.send_message("Only staff can claim tickets.", ephemeral=True)

        button.disabled = True
        await interaction.message.edit(view=self)
        
        embed = discord.Embed(title="Ticket Claimed", description=f"This ticket has been claimed by {interaction.user.mention}.", color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="open_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        tickets_cat = await get_or_create_tickets_category(guild)
        
        for ch in tickets_cat.text_channels:
            if ch.topic and f"ticket-owner:{user.id}" in ch.topic:
                return await interaction.response.send_message(f"You already have an open ticket: {ch.mention}", ephemeral=True)

        staff = get_staff_role(guild)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        if staff:
            overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{user.name}"[:90],
                category=tickets_cat,
                overwrites=overwrites,
                topic=f"ticket-owner:{user.id}",
            )
        except Exception as e:
            return await interaction.response.send_message(f"Couldn't create ticket channel: `{e}`", ephemeral=True)

        embed = discord.Embed(title="Ticket Opened", description=f"Thanks for reaching out, {user.mention}! A staff member will be with you shortly.", color=discord.Color.gold())
        await channel.send(content=user.mention, embed=embed, view=TicketActionView())
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

# ─── AUTO CLOSE TASK ────────────────────────────────────────────────

async def auto_close_tickets():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            for guild in client.guilds:
                tickets_cat = None
                for cat in guild.categories:
                    if cat.name == TICKETS_CATEGORY_NAME:
                        tickets_cat = cat
                        break
                
                if not tickets_cat:
                    continue

                for channel in tickets_cat.text_channels:
                    if not channel.topic or "ticket-owner:" not in channel.topic:
                        continue
                    
                    try:
                        last_message = [msg async for msg in channel.history(limit=1)]
                        if last_message:
                            last_msg_time = last_message[0].created_at.timestamp()
                            current_time = time.time()
                            
                            if current_time - last_msg_time > AUTO_CLOSE_SECONDS:
                                print(f"[Auto-Close] Closing inactive ticket: {channel.name}")
                                await channel.send("⏰ This ticket has been inactive for 24 hours and will now be closed automatically.")
                                await asyncio.sleep(2)
                                await channel.delete(reason="Auto-closed due to 24 hours of inactivity.")
                    except Exception as e:
                        print(f"[Auto-Close] Error checking {channel.name}: {e}")

        except Exception as e:
            print(f"[Auto-Close] Loop error: {e}")
            
        await asyncio.sleep(300)

# ─── COMMANDS ───────────────────────────────────────────────────────

@tree.command(name="panel", description="Spawn the ticket panel")
@app_commands.default_permissions(manage_guild=True)
async def panel_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="Help & Support", description="Click below to create a new support ticket 🎫", color=discord.Color.blurple())
    await interaction.channel.send(embed=embed, view=OpenTicketView())
    await interaction.response.send_message("Panel posted.", ephemeral=True)

# ─── STARTUP (WITH RAILWAY WEB SERVER) ──────────────────────────────

@client.event
async def on_ready():
    print(f"[+] Logged in as {client.user}")
    client.add_view(OpenTicketView())
    client.add_view(TicketActionView())
    
    # Start the auto-close task
    asyncio.create_task(auto_close_tickets())
    print("[+] Auto-close task started (24h inactivity)")
    
    try:
        synced = await tree.sync()
        print(f"[+] Synced {len(synced)} slash command(s) globally")
    except Exception as e:
        print(f"[!] sync failed: {e}")

# Simple web server just to keep Railway happy
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[+] Web server listening on port {PORT}")

async def main():
    await start_web_server()
    await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
