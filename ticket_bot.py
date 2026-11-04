#!/usr/bin/env python3
import os
import asyncio
import discord
from discord import app_commands
from aiohttp import web

# ==========================================
# CONFIG
# ==========================================
TOKEN = os.environ.get("TICKET_BOT_TOKEN")
TARGET_GUILD_ID = int(os.environ.get("TARGET_GUILD_ID", "1451327295682777151"))
STAFF_ROLE_ID = 1567348988284248064
TICKETS_CATEGORY_NAME = "Tickets"

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ─── helpers ────────────────────────────────────────────────
async def get_or_create_tickets_category(guild):
    for cat in guild.categories:
        if cat.name == TICKETS_CATEGORY_NAME:
            return cat
    return await guild.create_category(TICKETS_CATEGORY_NAME, reason="Ticket system")

def get_staff_role(guild):
    return guild.get_role(STAFF_ROLE_ID)

# ─── views ──────────────────────────────────────────────────
class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="NEED HELPS", style=discord.ButtonStyle.primary, emoji="🆘", custom_id="open_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        tickets_cat = await get_or_create_tickets_category(guild)
        for ch in tickets_cat.text_channels:
            if ch.topic and f"ticket-owner:{user.id}" in ch.topic:
                await interaction.response.send_message(f"You already have an open ticket: {ch.mention}", ephemeral=True)
                return

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
                reason=f"Ticket opened by {user}",
            )
        except Exception as e:
            await interaction.response.send_message(f"Couldn't create ticket channel: `{e}`", ephemeral=True)
            return

        embed = discord.Embed(title="Ticket Opened", description=f"{client.user.mention} has created a new 🆘 NEED HELPS ticket.", color=discord.Color.gold())
        await channel.send(content=user.mention, embed=embed, view=TicketActionView())

        auto_embed = discord.Embed(
            title="Support Ticket",
            description=f"Hello {user.mention}, thanks for reaching out!\n\nPlease provide as much detail as possible. A staff member will be with you shortly.\n\n*You can close this ticket at any time by clicking the button above.*",
            color=discord.Color.green()
        )
        mention_staff = staff.mention if staff else ""
        await channel.send(content=mention_staff, embed=auto_embed)
        await interaction.response.send_message(f"Ticket created: {channel.mention}", ephemeral=True)

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
            await interaction.response.send_message("Only the ticket opener or staff can close this.", ephemeral=True)
            return

        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        try:
            await asyncio.sleep(2)
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception as e:
            print(f"[!] close delete failed: {e}")

    @discord.ui.button(label="Claim Ticket", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="claim_ticket_btn")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        staff = get_staff_role(guild)
        is_staff = staff in interaction.user.roles if staff else False
        if not is_staff:
            await interaction.response.send_message("Only staff can claim tickets.", ephemeral=True)
            return

        button.disabled = True
        await interaction.message.edit(view=self)

        embed = discord.Embed(title="Ticket Claimed", description=f"This ticket has been claimed by {interaction.user.mention}.", color=discord.Color.gold())
        await interaction.response.send_message(content=interaction.user.mention, embed=embed, allowed_mentions=discord.AllowedMentions(users=True))

# ─── commands ───────────────────────────────────────────────
@tree.command(name="panel", description="Spawn the ticket panel")
@app_commands.default_permissions(manage_guild=True)
async def panel_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Help & Support",
        description="Click below to create a new support ticket 🎫\nAfg ticket",
        color=discord.Color.blurple()
    )
    await interaction.channel.send(embed=embed, view=OpenTicketView())
    await interaction.response.send_message("Panel posted.", ephemeral=True)

# ─── startup & sync ─────────────────────────────────────────
@client.event
async def on_ready():
    print(f"[+] Logged in as {client.user}")
    client.add_view(OpenTicketView())
    client.add_view(TicketActionView())

    guild_obj = discord.Object(id=TARGET_GUILD_ID)
    
    try:
        tree.copy_global_to(guild=guild_obj)
        synced = await tree.sync(guild=guild_obj)
        print(f"[+] Synced {len(synced)} slash commands to guild {TARGET_GUILD_ID}")
    except Exception as e:
        print(f"[!] Guild sync failed: {e}")

    try:
        await tree.sync()
        print("[+] Global sync sent.")
    except Exception as e:
        print(f"[!] Global sync failed: {e}")

    print("[+] Ready. Run /panel to post the ticket panel.")
    
    # Start the fake web server for Render
    asyncio.create_task(start_web_server())

# ─── Fake Web Server ────────────────────────────────────────
async def start_web_server():
    app = web.Application()
    async def health(request):
        return web.Response(text="Bot is alive!")
    
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[+] Web server listening on port {port}")

# ─── main ───────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing TICKET_BOT_TOKEN environment variable")
    client.run(TOKEN)
