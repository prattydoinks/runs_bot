import asyncio
import discord
import re
import functools
import sqlite3
from discord.ext import commands
from discord.commands import Option
from collections import Counter
import datetime

conn = sqlite3.connect("runs.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    runner_id INTEGER,
    runner_name TEXT,
    type TEXT,
    ladder TEXT,
    run_name TEXT,
    attendees TEXT,
    start_time TIMESTAMP
);
""")

conn.commit()

class JoinRunView(discord.ui.View):
    def __init__(self, run_id, timeout=850):  # Max timeout = 15 minutes
        super().__init__(timeout=timeout)
        self.run_id = run_id
        self.message = None  # Store the message reference

        join_button = discord.ui.Button(style=discord.ButtonStyle.green, label="Join Run")
        join_button.callback = functools.partial(join_run_callback, run_id=self.run_id)
        self.add_item(join_button)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True  # Disable buttons
        if self.message:
            await self.message.edit(view=self)

class MyModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.add_item(discord.ui.InputText(label="Runs Name"))
        self.add_item(discord.ui.InputText(label="Password", required=False))
        self.run_name = None
        self.password = ''

    async def callback(self, interaction: discord.Interaction):
        embed = discord.Embed(title="Run Info")
        embed.add_field(name="Runs Name", value=self.children[0].value)
        embed.add_field(name="Password", value=self.children[1].value)
        self.run_name = self.children[0].value.strip()
        self.password = self.children[1].value.strip()
        await interaction.response.send_message('Run Info Established!')
        self.stop()

active_runs = {}
runs_num = 0
run_timeouts = {}
cursor_lock = asyncio.Lock()
active_runs_lock = asyncio.Lock()
run_timeouts_lock = asyncio.Lock()

TOKEN = "YOUR_TOKEN_HERE"
intents = discord.Intents.all()
bot = commands.Bot(intents=intents)
guild_ids = [<YOUR_GUILD_ID_HERE_AS_INT>]

async def remove_run_after_timeout(run_owner):
    await asyncio.sleep(2 * 60 * 60)  # 1.5 hours
#    await asyncio.sleep(10)  # 10 seconds
    async with active_runs_lock:
        if run_owner in active_runs:
            del active_runs[run_owner]
            if run_owner in run_timeouts:
                del run_timeouts[run_owner]

@bot.event
async def on_ready():
    print('Ready!')

def add_player_to_run_db(runner_id, attendee):
    global conn
    cursor.execute("SELECT * FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1", (runner_id,))
    db_result = cursor.fetchone()
    if db_result:
        my_attendees = db_result[6].split(",")
    else:
        my_attendees = []
    my_attendees.append(attendee)
    my_attendees = ",".join(my_attendees)
#    print(my_attendees)
    cursor.execute("""
        UPDATE runs
        SET attendees = ?
        WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
    """, (my_attendees, runner_id))

    conn.commit()
    return

def del_player_from_run_db(runner_id, attendee):
    global conn
    cursor.execute("SELECT * FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1", (runner_id,))
    db_result = cursor.fetchone()
    if db_result:
        my_attendees = db_result[6].split(",")
        my_attendees.remove(attendee)
        my_attendees = ",".join(my_attendees)
        cursor.execute("""
            UPDATE runs
            SET attendees = ?
            WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
        """, (my_attendees, runner_id))

        conn.commit()
    return

@bot.slash_command(name="command_help", description="Get a list of the commands for the Runs bot", guild_ids=guild_ids)
async def command_help(ctx):
    commands_string = '''
These are the commands: /host /ng /runs /end /leave /add /kick /change_runner /rename /top_runners /top_participants /top_monthly_runners /top_monthly_participants /leaderboard

/host starts a new game with a few options
/ng creates a new game
/runs will show available and non-available runs with join buttons depending and YOUR game's info if you're joined
/end will close out an instance of a run and is for the host's use
/leave will make you leave a tracked game only if you are a participant
/add will allow you to add someone from the server to your run
/kick will allow you to kick someone from your run except for the host
/change_runner will allow the host to choose a new runner
/rename allows you to update your run name and password
/top_hosts and top_participants are self explanatory
/top_monthly_hosts /top_monthly_participants pull the top ten entries respectively from the last 30 days
/leaderboard shows you all relevant stats at once
'''

    await ctx.respond(commands_string, ephemeral=True)

@bot.slash_command(name="add", description="Add a player to your game.", guild_ids=guild_ids)
async def add(ctx, player: Option(discord.Member, "Select a player to add.")):
    global active_runs
    user = ctx.author
    if user in active_runs.keys():
        run_info = active_runs[user]
        if len(run_info['attendees']) < 7:
            if player != user and player not in run_info['attendees']:
                async with active_runs_lock:
                    run_info['attendees'].append(player)
                async with cursor_lock:
                    add_player_to_run_db(user.id, player.name)
                await ctx.respond(f"{player.mention} has been added to your run.", ephemeral=True)
            elif player == user:
                try:
                    await ctx.respond("You can't add yourself to your own run.", ephemeral=True)
                except:
                    await ctx.followup.send("You can't add yourself to your own run.", ephemeral=True)
            else:
                await ctx.respond(f"{player.mention} is already in your run.", ephemeral=True)
        else:
            await ctx.respond("Your run is already full.", ephemeral=True)
    else:
        for run in active_runs.keys():
            run_info = active_runs[run]
            if len(run_info['attendees']) < 7:
               if ctx.author in run_info['attendees'] and player not in run_info['attendees']:
                    async with active_runs_lock:
                        run_info['attendees'].append(player)
                    async with cursor_lock:
                        add_player_to_run_db(run.id, player.name)
                    await ctx.respond(f"{player.mention} has been added to your run.", ephemeral=True)
               else:
                   await ctx.respond(f"{player.mention} is already in a run.", ephemeral=True)
            else:
                await ctx.respond(f"Run is full.", ephemeral=True)


@bot.slash_command(name="rename", description="Change the game name and password of your run.", guild_ids=guild_ids)
async def rename(ctx):
    global active_runs

    user = ctx.author

    # Check if the user is hosting a run
    if user not in active_runs:
        await ctx.respond("You are not currently hosting a run.", ephemeral=True)
        return

    modal = MyModal(title="Input for run")
    await ctx.send_modal(modal)
    await modal.wait()
    # Update the run information in active_runs
    async with active_runs_lock:
        active_runs[user]['runs_name'] = modal.run_name
        active_runs[user]['runs_password'] = modal.password

    # Update the database
    async with cursor_lock:
        cursor.execute("""
            UPDATE runs
            SET run_name = ?
            WHERE runner_id = (SELECT runner_id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
        """, (modal.run_name, user.id))  # Reset attendees list if needed
        conn.commit()

    # Send a confirmation message
    await ctx.respond(f"{user.mention}'s game name and password have been updated!")

@bot.slash_command(name="change_runner", description="Transfer ownership of your run to another player.", guild_ids=guild_ids)
async def change_runner(ctx, 
                        new_runner: Option(discord.Member, "Select a new runner.")):
    global active_runs

    user = ctx.author  # Current runner

    # Check if the user is hosting a run
    if user not in active_runs.keys():
        await ctx.respond("You are not currently hosting a run.", ephemeral=True)
        return

    run_info = active_runs[user]

    async with active_runs_lock:
        active_runs[new_runner] = run_info  # Copy the run details to the new runner
        del active_runs[user]  # Remove the old runner entry
        active_runs[new_runner]['runner'] = new_runner  # Update the runner info
        run_timeouts[ctx.author].cancel()
        timeout_task = asyncio.create_task(remove_run_after_timeout(new_runner))
        run_timeouts[new_runner] = timeout_task

    async with cursor_lock:
        cursor.execute("""
            UPDATE runs
            SET runner_id = ?, runner_name = ?
            WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
        """, (new_runner.id, new_runner.name, user.id))
        conn.commit()

    if new_runner in run_info['attendees']:
        async with active_runs_lock:
            run_info['attendees'].remove(new_runner)  # Remove old runner from attendees

        async with cursor_lock:
            del_player_from_run_db(new_runner.id, new_runner.name)  # Remove from DB attendees

    await ctx.respond(f"{user.mention}'s run has been transferred! {new_runner.mention} is now the new host.")

@bot.slash_command(name="kick", description="Kick a player from your game.", guild_ids=guild_ids)
async def kick(ctx, player: Option(discord.Member, "Select a player to kick.")):
    global active_runs
    user = ctx.author
    if user in active_runs.keys():
        run_info = active_runs[user]
        if player in run_info['attendees']:
            async with active_runs_lock:
                run_info['attendees'].remove(player)
            async with cursor_lock:
                del_player_from_run_db(user.id, player.name)
            await ctx.respond(f"{player.mention} has been kicked from your run.", ephemeral=True)
            return
        else:
            await ctx.respond(f"{player.mention} is not in your run.", ephemeral=True)
            return
    else:
        for run in active_runs.keys():
            run_info = active_runs[run]
            if ctx.author in run_info['attendees'] and player in run_info['attendees']:
                async with active_runs_lock:
                    run_info['attendees'].remove(player)
                async with cursor_lock:
                    del_player_from_run_db(run.id, player.name)
                await ctx.respond(f"{player.mention} has been kicked from your run.", ephemeral=True)
                return
    await ctx.respond("Player is not in game.")

@bot.slash_command(name="host", description="Host a new game", guild_ids=guild_ids)
async def host(ctx,
               ladder: Option(str, "Ladder or non-ladder", choices=["Non-Ladder", "Ladder", "Non-Ladder Hardcore", "Ladder Hardcore"], required=True),
               type: Option(str, "What type of run is this?", choices=["Baal", "Pre-Tele Baal", "Chaos-Full Clear", "Chaos-Seal Pop", "Cows", "Tombs", "Split-Tombs", "TZ", "GRush"], required=True)):
    global active_runs
    global runs_num
    in_run = False
    for runner in active_runs.values():
        if ctx.author in runner['attendees']:
            in_run = True
    if ctx.author not in active_runs.keys() and in_run == False:
        if runs_num > 999:
            runs_num = 0
        runs_num += 1
        modal = MyModal(title="Input for run")
        await ctx.send_modal(modal)
        await modal.wait()
        async with active_runs_lock:
            active_runs[ctx.author] = { 'ladder': ladder, 'type': type, 'runner': ctx.author,
                                        'attendees': [], 'runs_num': runs_num,
                                        'runs_name': modal.run_name, 'runs_password': modal.password, }
        timeout_task = asyncio.create_task(remove_run_after_timeout(ctx.author))
        async with run_timeouts_lock:
            run_timeouts[ctx.author] = timeout_task

        async with cursor_lock:
            cursor.execute("""
                INSERT INTO runs (runner_id, runner_name, type, ladder, run_name, attendees, start_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (ctx.author.id, ctx.author.name, type, ladder, modal.run_name, "", datetime.datetime.now(datetime.UTC)))

            conn.commit()

        view = JoinRunView(run_id=ctx.author, timeout=850)
        message = await ctx.respond(f"**`NEW RUN ALERT!`**\nJoin {type} runs on\n# {ladder}\nhosted by {ctx.author.mention}!", view=view)
        view.message = message
    else:
        await ctx.respond("You are already hosting a run!", ephemeral=True)

@bot.slash_command(name="end", description="End a run", guild_ids=guild_ids)
async def end(ctx):
    global active_runs
    global runs_num
    if ctx.author in active_runs.keys():
        async with active_runs_lock:
            del active_runs[ctx.author]
        await ctx.respond(f"{ctx.author.mention} has ended the run.")
    else:
        await ctx.respond("No runs exist under your user.", ephemeral=True)
    if ctx.author in run_timeouts:
        async with run_timeouts_lock:
            run_timeouts[ctx.author].cancel()
        del run_timeouts[ctx.author]

async def join_run_callback(interaction: discord.Interaction, run_id):
    async with active_runs_lock:
        run_info = active_runs.get(run_id)
    if run_info:
        has_available_spots = len(run_info['attendees']) < 7
        available_spots = 7 - len(run_info['attendees'])
        user = interaction.user
        existing_run = None
        for run in active_runs.values():
            if user in run['attendees']:
                existing_run = run
                break
        if user in active_runs.keys():
            existing_run = run
        if existing_run:
            await interaction.response.send_message(content=f"{user.mention} you are already in a game!", ephemeral=True)
        if user in active_runs.keys():
            await interaction.response.send_message(content="You can't host and join at the same time.", ephemeral=True)
        elif len(run_info['attendees']) < 7 and not existing_run:
            if user not in run_info['attendees']:
                async with active_runs_lock:
                   run_info['attendees'].append(user)
                async with cursor_lock:
                    add_player_to_run_db(run_id.id, user.name)
                available_spots = 7 - len(run_info['attendees'])
                game_info_message = f"Game Name: {run_info['runs_name']}\nGame Password: {run_info['runs_password']}"
                await interaction.response.send_message(content=game_info_message, ephemeral=True)  # Send game details privately to the joining user
            if available_spots > 0:
                view = JoinRunView(run_id=run_info['runner'], timeout=850)
                message = await interaction.followup.send(content=f"{user.mention} has been added to {run_info['runner'].mention}'s\n# {run_info['ladder']}\n{run_info['type']} run. There are {available_spots} spots left.", view=view)
                view.message = message
            else:
                await interaction.followup.send(content=f"{user.mention} has been added to {run_info['runner'].mention}'s\n# {run_info['ladder']}\n{run_info['type']} run. There are {available_spots} spots left.")
        else:
            await interaction.response.send_message(content="You are already in a run, or the run is full.", ephemeral=True)
    else:
        await interaction.response.send_message(content="The run no longer exists.", ephemeral=True)

@bot.slash_command(name="runs", description="Show current runs.", guild_ids=guild_ids)
async def runs(ctx):
    if len(active_runs) > 0:
        for run in active_runs.keys():
            run_info = active_runs[run]
            has_available_spots = len(run_info['attendees']) < 7
            run_num = str(active_runs[run]['runs_num'])
            runner = run
            ladder = active_runs[run]['ladder']
            type = active_runs[run]['type']
            name = active_runs[run]['runs_name']
            password = active_runs[run]['runs_password']
            attendees = active_runs[run]['attendees']
            if ctx.author in attendees:
                message = f"Game Name: {str(name)}\nGame Password: {password}\nRunner: {runner.name}\n# {ladder}\nType: {type}\n"
            elif ctx.author.id == runner.id:
                message = f"Game Name: {str(name)}\nGame Password: {password}\nRunner: {runner.name}\n# {ladder}\nType: {type}\n"
            else:
                message = f"Runner: {runner.mention}\n# {ladder}\nType: {type}\n"
            message += "Attendees:\n"
            for attendee in attendees:
                message += f"{attendee.mention}\n"
            message += "\n\n"
            if has_available_spots:
                view = JoinRunView(run_id=runner, timeout=850)
                message = await ctx.respond(message, view=view, ephemeral=True)
                view.message = message
            else:
                await ctx.respond(message, ephemeral=True)
    else:
        await ctx.respond("There are no current runs.", ephemeral=True)

@bot.slash_command(name="leave", description="Leave a run.", guild_ids=guild_ids)
async def leave(ctx):
    global active_runs

    # Check if the user is the runner of any game
    if ctx.author in active_runs:
        await ctx.respond("You are the runner of this game! Use /end to end the game instead.", ephemeral=True)
        return
    for runner in active_runs.keys():
        if ctx.author in active_runs[runner]['attendees']:
            async with active_runs_lock:
                active_runs[runner]['attendees'].remove(ctx.author)
            spots_available = 7 - len(active_runs[runner]['attendees'])
            view = JoinRunView(run_id=runner, timeout=850)
            async with cursor_lock:
                del_player_from_run_db(runner.id, ctx.author.name)
            message = await ctx.respond(f"{ctx.author.mention} has left the\n# {active_runs[runner]['ladder']}\n{active_runs[runner]['type']} run. There are {spots_available} spots available in {runner.mention}'s runs.", view=view)
            view.message = message
            return

    await ctx.respond("You are not part of any runs.", ephemeral=True)

@bot.slash_command(name="ng", description="Increment your run", guild_ids=guild_ids)
async def ng(ctx):
    global active_runs
    async with run_timeouts_lock:
        if ctx.author in run_timeouts:
            run_timeouts[ctx.author].cancel()
            timeout_task = asyncio.create_task(remove_run_after_timeout(ctx.author))
            run_timeouts[ctx.author] = timeout_task
        else:
            for runner in active_runs.keys():
                for attendee in active_runs[runner]['attendees']:
                    if attendee == ctx.author:
                        my_run = active_runs[runner]
                        run_timeouts[runner].cancel()
                        timeout_task = asyncio.create_task(remove_run_after_timeout(runner))
                        run_timeouts[runner] = timeout_task

    if ctx.author in active_runs.keys():
        async with active_runs_lock:
            my_run = active_runs[ctx.author]
            run_name = my_run['runs_name']
            matches = re.findall("[0-9]*$", run_name)
            match = matches[0]
            if match == "":
                run_name = run_name + "-1"
            else:
                new_match = str(int(match) + 1).zfill(len(match))
                run_name = run_name.replace(match, new_match)
            active_runs[ctx.author]['runs_name'] = run_name
        async with cursor_lock:
            cursor.execute("SELECT * FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1", (ctx.author.id,))
            db_result = cursor.fetchone()
            cursor.execute("""
                INSERT INTO runs (runner_id, runner_name, type, ladder, run_name, attendees, start_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ctx.author.id, ctx.author.name, db_result[3], db_result[4], db_result[5], db_result[6], datetime.datetime.now(datetime.UTC)))

            conn.commit()
        await ctx.respond(f"New run at: {run_name}", ephemeral=True)
    else:
        for runner in active_runs.keys():
            for attendee in active_runs[runner]['attendees']:
                if attendee == ctx.author:
                    my_run = active_runs[runner]
                    run_name = my_run['runs_name']
                    matches = re.findall("[0-9]*$", run_name)
                    match = matches[0]
                    if match == "":
                        run_name = run_name + "-1"
                    else:
                        new_match = str(int(match) + 1).zfill(len(match))
                        run_name = run_name.replace(match, new_match)
                    async with active_runs_lock:
                        active_runs[runner]['runs_name'] = run_name
                    async with cursor_lock:
                        cursor.execute("SELECT * FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1", (runner.id,))
                        db_result = cursor.fetchone()
                        cursor.execute("""
                            INSERT INTO runs (runner_id, runner_name, type, ladder, run_name, attendees, start_time)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (runner.id, runner.name, db_result[3], db_result[4], db_result[5], db_result[6], datetime.datetime.now(datetime.UTC)))
                        conn.commit()
                    await ctx.respond(f"New run at: {run_name}", ephemeral=True)

def get_top_runners_last_month():
    cursor.execute("""
        SELECT runner_name, COUNT(*) as total_runs
        FROM runs
        WHERE start_time >= DATE('now', '-1 month')
        GROUP BY runner_id
        ORDER BY total_runs DESC
        LIMIT 10
    """)
    return cursor.fetchall()

@bot.slash_command(name="top_hosts", description="Get top players who hosted the most runs", guild_ids=guild_ids)
async def top_hosts(ctx):
    async with cursor_lock:
        cursor.execute("""
            SELECT runner_name, COUNT(*) as total_runs FROM runs 
            GROUP BY runner_id ORDER BY total_runs DESC LIMIT 10
        """)
        result = cursor.fetchall()

    if not result:
        await ctx.respond("No one has hosted any runs yet.", ephemeral=True)
        return

    message = "**Top Hosts:**\n"
    for index, (runner, total_runs) in enumerate(result, start=1):
        message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"

    await ctx.respond(message, ephemeral=True)

@bot.slash_command(name="top_monthly_hosts", description="Get top players who hosted the most runs this past month.", guild_ids=guild_ids)
async def top_monthly_hosts(ctx):
    async with cursor_lock:
        result = get_top_runners_last_month()
    if not result:
        await ctx.respond("No one has hosted any runs yet.", ephemeral=True)
        return

    message = "**Top Hosts for the Last 30 Days:**\n"
    for index, (runner, total_runs) in enumerate(result, start=1):
        message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"
    await ctx.respond(message, ephemeral=True)

@bot.slash_command(name="top_participants", description="Get top players who participated in the most runs", guild_ids=guild_ids)
async def top_participants(ctx):
    async with cursor_lock:
        cursor.execute("""
            SELECT * FROM runs
        """)
        results = cursor.fetchall()
    all_users = []
    if not results:
        await ctx.respond("No one has hosted any runs yet.", ephemeral=True)
        return
    for result in results:
        all_users.extend(result[6].split(","))
#    print(all_users)
    counted = Counter(all_users)
    sorted_dict = dict(sorted(counted.most_common(11)))
    sorted_list_sanitized = [(v, k) for k, v in sorted_dict.items() if k != '']
    sorted_list_sanitized = sorted(sorted_list_sanitized, reverse=True)
    message = "**Top Participants:**\n"
    i = 1
    for v, k in sorted_list_sanitized:
        if i == 11:
            break
        message += f"`{i}. {k}: Participated in {v} Runs`\n"
        i += 1
    await ctx.respond(message, ephemeral=True)

@bot.slash_command(name="top_monthly_participants", description="Get top players who participated in the most runs this month", guild_ids=guild_ids)
async def top_monthly_participants(ctx):
    async with cursor_lock:
        cursor.execute("""
            SELECT * FROM runs
            WHERE start_time >= DATE('now', '-1 month')
        """)
        results = cursor.fetchall()
    all_users = []
    if not results:
        await ctx.respond("No one has hosted any runs yet.", ephemeral=True)
        return
    for result in results:
        all_users.extend(result[6].split(","))
#    print(all_users)
    counted = Counter(all_users)
    sorted_dict = dict(sorted(counted.most_common(11)))
    sorted_list_sanitized = [(v, k) for k, v in sorted_dict.items() if k != '']
    sorted_list_sanitized = sorted(sorted_list_sanitized, reverse=True)
    message = "**Top Participants in the Last 30 Days:**\n"
    i = 1
    for v, k in sorted_list_sanitized:
        if i == 11:
            break
        message += f"`{i}. {k}: Participated in {v} Runs`\n"
        i += 1
    await ctx.respond(message, ephemeral=True)

@bot.slash_command(name="leaderboard", description="Get top players who participated in/hosted the most runs this month and all-time", guild_ids=guild_ids)
async def leaderboard(ctx):
    result = get_top_runners_last_month()
    message = "**Top Hosts for the Last 30 Days:**\n"
    for index, (runner, total_runs) in enumerate(result, start=1):
        message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"

    async with cursor_lock:
        cursor.execute("""
            SELECT runner_name, COUNT(*) as total_runs FROM runs
            GROUP BY runner_id ORDER BY total_runs DESC LIMIT 10
        """)
        result = cursor.fetchall()

    message += "\n**Top Hosts All-Time:**\n"
    for index, (runner, total_runs) in enumerate(result, start=1):
        message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"

    async with cursor_lock:
        cursor.execute("""
            SELECT * FROM runs
            WHERE start_time >= DATE('now', '-1 month')
        """)
        results = cursor.fetchall()
    all_users = []
    for result in results:
        all_users.extend(result[6].split(","))
    counted = Counter(all_users)
    sorted_dict = dict(sorted(counted.most_common(11)))
    sorted_list_sanitized = [(v, k) for k, v in sorted_dict.items() if k != '']
    sorted_list_sanitized = sorted(sorted_list_sanitized, reverse=True)
    message += "\n**Top Participants in the Last 30 Days:**\n"
    i = 1
    for v, k in sorted_list_sanitized:
            if i == 11:
                break
            message += f"`{i}. {k}: Participated in {v} Runs`\n"
            i += 1

    async with cursor_lock:
        cursor.execute("""
            SELECT * FROM runs
        """)
        results = cursor.fetchall()
    all_users = []
    for result in results:
        all_users.extend(result[6].split(","))
    counted = Counter(all_users)
    sorted_dict = dict(sorted(counted.most_common(11)))
    sorted_list_sanitized = [(v, k) for k, v in sorted_dict.items() if k != '']
    sorted_list_sanitized = sorted(sorted_list_sanitized, reverse=True)
    message += "\n**Top Participants All-Time:**\n"
    i = 1
    for v, k in sorted_list_sanitized:
            if i == 11:
                break
            message += f"`{i}. {k}: Participated in {v} Runs`\n"
            i += 1
    await ctx.respond(message, ephemeral=True)

bot.run(TOKEN)
