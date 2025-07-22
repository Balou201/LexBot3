import discord
from discord.ext import commands
from discord.ui import View, Button, Select
import asyncio
import sqlite3

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

ROLE_ALERT_PERMISSION = 1395396802999746600
ROLE_BANNED = 1396893902715486298
CHANNEL_ALERT_ID = 1395397933758808238
CHANNEL_LOG_ID = 1387542394295029820

# --- Base de données SQLite ---
conn = sqlite3.connect('alertes.db')
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS alertes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    executor_id INTEGER NOT NULL,
    raison TEXT NOT NULL,
    sanction TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')
conn.commit()

# Sanctions automatiques par nombre d'alertes
automatic_sanctions = {
    1: "Avertissement",
    2: "Mute temporaire (1h)",
    3: "Ban (rôle ajouté)"
}

# Vue avec les boutons d'action
class AlertActionView(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=None)
        self.member = member

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger)
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(ROLE_BANNED)
        if role:
            await self.member.add_roles(role)
            await interaction.response.send_message(f"{self.member.mention} a été banni (rôle ajouté).", ephemeral=False)
        else:
            await interaction.response.send_message("Rôle de ban introuvable.", ephemeral=True)

    @discord.ui.button(label="Exclusion Temporaire", style=discord.ButtonStyle.secondary)
    async def temp_exclude_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choisis la durée de l'exclusion :", view=ExclusionDurationView(self.member), ephemeral=True)

# Vue avec les durées d’exclusion temporaire
class ExclusionDurationView(View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=60)
        self.member = member

    @discord.ui.select(
        placeholder="Sélectionne une durée",
        options=[
            discord.SelectOption(label="1 heure", value="1"),
            discord.SelectOption(label="6 heures", value="6"),
            discord.SelectOption(label="12 heures", value="12"),
            discord.SelectOption(label="24 heures", value="24"),
            discord.SelectOption(label="48 heures", value="48"),
        ]
    )
    async def select_duration(self, interaction: discord.Interaction, select: discord.ui.Select):
        duration_hours = int(select.values[0])
        role = interaction.guild.get_role(ROLE_BANNED)
        if role:
            await self.member.add_roles(role)
            await interaction.response.send_message(f"{self.member.mention} exclu temporairement pour {duration_hours}h.", ephemeral=False)
            await asyncio.sleep(duration_hours * 3600)
            await self.member.remove_roles(role)
        else:
            await interaction.response.send_message("Rôle d’exclusion introuvable.", ephemeral=True)

# Fonction pour récupérer le nombre d'alertes d'un membre dans la base
def get_alert_count(member_id: int) -> int:
    c.execute('SELECT COUNT(*) FROM alertes WHERE member_id = ?', (member_id,))
    result = c.fetchone()
    return result[0] if result else 0

# Fonction pour ajouter une alerte dans la base
def add_alert(member_id: int, executor_id: int, raison: str, sanction: str | None):
    c.execute(
        'INSERT INTO alertes (member_id, executor_id, raison, sanction) VALUES (?, ?, ?, ?)',
        (member_id, executor_id, raison, sanction)
    )
    conn.commit()

# Fonction pour appliquer sanction automatique
async def apply_automatic_sanction(guild: discord.Guild, member: discord.Member, count_alerts: int):
    sanction = automatic_sanctions.get(count_alerts)
    role = guild.get_role(ROLE_BANNED)

    if sanction == "Avertissement":
        return sanction

    elif sanction == "Mute temporaire (1h)":
        if role:
            await member.add_roles(role)
            await asyncio.sleep(3600)
            await member.remove_roles(role)
        return sanction

    elif sanction == "Ban (rôle ajouté)":
        if role:
            await member.add_roles(role)
        return sanction

    else:
        return "Pas de sanction automatique"

@bot.command(name="alerte")
async def alerte(ctx, nom_joueur: str, raison: str, *, sanction: str = None):
    if ROLE_ALERT_PERMISSION not in [role.id for role in ctx.author.roles]:
        await ctx.send("Tu n'as pas la permission d'utiliser cette commande.")
        return

    channel_alert = bot.get_channel(CHANNEL_ALERT_ID)
    channel_log = bot.get_channel(CHANNEL_LOG_ID)
    if channel_alert is None or channel_log is None:
        await ctx.send("Salon d’alerte ou de log introuvable.")
        return

    member = discord.utils.find(lambda m: m.name == nom_joueur, ctx.guild.members)
    if not member:
        await ctx.send("Joueur introuvable sur le serveur.")
        return

    # Récupérer nombre d'alertes
    count_alerts = get_alert_count(member.id) + 1

    # Ajouter l'alerte en base, avec sanction (manuelle ou à compléter)
    add_alert(member.id, ctx.author.id, raison, sanction)

    # Appliquer sanction automatique si pas de sanction manuelle
    sanction_auto = await apply_automatic_sanction(ctx.guild, member, count_alerts)
    sanction_finale = sanction if sanction else sanction_auto

    # Envoyer message dans salon alerte
    embed = discord.Embed(
        title="🚨 Alerte Joueur",
        description=(
            f"**Nom :** {nom_joueur}\n"
            f"**Raison :** {raison}\n"
            f"**Sanction :** {sanction_finale}\n"
            f"**Nombre d'alertes :** {count_alerts}"
        ),
        color=discord.Color.red()
    )
    await channel_alert.send(embed=embed, view=AlertActionView(member))

    # Envoyer DM au joueur
    try:
        await member.send(
            f"Tu as reçu une alerte sur le serveur.\nRaison : {raison}\nSanction : {sanction_finale}"
        )
    except Exception:
        pass

    # Envoyer log dans salon log
    executor_name = ctx.author.name if ctx.author else "Bot"
    log_embed = discord.Embed(
        title="📝 Rapport d'alerte",
        description=(
            f"**Joueur visé :** {nom_joueur}\n"
            f"**Raison :** {raison}\n"
            f"**Sanction :** {sanction_finale}\n"
            f"**Effectué par :** {executor_name}\n"
            f"**Type :** {'Manuel' if sanction else 'Automatique'}"
        ),
        color=discord.Color.blue()
    )
    await channel_log.send(embed=log_embed)

    await ctx.send(f"Alerte enregistrée pour {nom_joueur} avec sanction : {sanction_finale}")

import os

TOKEN = os.environ.get("DISCORD_TOKEN")
bot.run(TOKEN)
