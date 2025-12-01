import asyncio
import discord
import re
import sqlite3
from discord.ext import commands
from discord.commands import Option
from collections import Counter
import datetime

class Run:
    def __init__(self, runner: discord.Member, ladder: str, run_type: str, run_name: str, password: str):
        self.runner = runner
        self.ladder = ladder
        self.type = run_type
        self.run_name = run_name
        self.password = password
        self.attendees = []
        self.start_time = datetime.datetime.now(datetime.UTC)

    def get_realm(self) -> int | None:
        HARDCORE_LAD = 1356339382323249312
        HARDCORE_NONLAD = 1337609082290573404
        SOFTCORE_LAD = 1337608997997510732
        SOFTCORE_NONLAD = 1337608670661316678
        if self.ladder == "Non-Ladder":
            return SOFTCORE_NONLAD
        elif self.ladder == "Ladder":
            return SOFTCORE_LAD
        elif self.ladder == "Non-Ladder Hardcore":
            return HARDCORE_NONLAD
        elif self.ladder == "Ladder Hardcore":
            return HARDCORE_LAD
        else:
            return None

class Database:
    def __init__(self, db_name="runs.db"):
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.lock = asyncio.Lock()
        self.create_table()

    def create_table(self):
        self.cursor.execute("""
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
        self.conn.commit()

    async def insert_run(self, run: Run):
        attendees_str = ",".join([a.name for a in run.attendees])
        async with self.lock:
            self.cursor.execute("""
                INSERT INTO runs (runner_id, runner_name, type, ladder, run_name, attendees, start_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (run.runner.id, run.runner.name, run.type, run.ladder, run.run_name, attendees_str, run.start_time))
            self.conn.commit()

    async def update_run_name(self, runner_id: int, run_name: str):
        async with self.lock:
            self.cursor.execute("""
                UPDATE runs
                SET run_name = ?
                WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
            """, (run_name, runner_id))
            self.conn.commit()

    async def add_attendee(self, runner_id: int, attendee_name: str):
        async with self.lock:
            self.cursor.execute("SELECT attendees FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1", (runner_id,))
            result = self.cursor.fetchone()
            if result:
                attendees = result[0].split(",") if result[0] else []
                if attendee_name not in attendees:
                    attendees.append(attendee_name)
                    attendees_str = ",".join(attendees)
                    self.cursor.execute("""
                        UPDATE runs
                        SET attendees = ?
                        WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
                    """, (attendees_str, runner_id))
                    self.conn.commit()

    async def remove_attendee(self, runner_id: int, attendee_name: str):
        async with self.lock:
            self.cursor.execute("SELECT attendees FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1", (runner_id,))
            result = self.cursor.fetchone()
            if result:
                attendees = result[0].split(",") if result[0] else []
                if attendee_name in attendees:
                    attendees.remove(attendee_name)
                    attendees_str = ",".join(attendees)
                    self.cursor.execute("""
                        UPDATE runs
                        SET attendees = ?
                        WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
                    """, (attendees_str, runner_id))
                    self.conn.commit()

    async def update_runner(self, old_runner_id: int, new_runner_id: int, new_runner_name: str):
        async with self.lock:
            self.cursor.execute("""
                UPDATE runs
                SET runner_id = ?, runner_name = ?
                WHERE id = (SELECT id FROM runs WHERE runner_id = ? ORDER BY id DESC LIMIT 1)
            """, (new_runner_id, new_runner_name, old_runner_id))
            self.conn.commit()

    async def get_top_hosts(self, last_month: bool = False):
        query = """
            SELECT runner_name, COUNT(*) as total_runs
            FROM runs
            GROUP BY runner_id
            ORDER BY total_runs DESC
            LIMIT 10
        """
        if last_month:
            query = query.replace("FROM runs", "FROM runs WHERE start_time >= DATE('now', '-1 month')")
        async with self.lock:
            self.cursor.execute(query)
            return self.cursor.fetchall()

    async def get_all_attendees_strings(self, last_month: bool = False):
        query = "SELECT attendees FROM runs"
        if last_month:
            query += " WHERE start_time >= DATE('now', '-1 month')"
        async with self.lock:
            self.cursor.execute(query)
            return [row[0] for row in self.cursor.fetchall()]

async def get_top_participants(db: Database, last_month: bool = False):
    all_attendees_str = await db.get_all_attendees_strings(last_month)
    all_users = []
    for s in all_attendees_str:
        all_users.extend(s.split(",") if s else [])
    counted = Counter([u for u in all_users if u])
    return counted.most_common(10)

class RunManager:
    def __init__(self):
        self.active_runs: dict[discord.Member, Run] = {}
        self.timeouts: dict[discord.Member, asyncio.Task] = {}
        self.lock = asyncio.Lock()
        self.timeouts_lock = asyncio.Lock()

    async def add_run(self, run: Run):
        async with self.lock:
            if run.runner in self.active_runs:
                raise ValueError("Runner already hosting a run")
            self.active_runs[run.runner] = run
        timeout_task = asyncio.create_task(self._remove_after_timeout(run.runner))
        async with self.timeouts_lock:
            self.timeouts[run.runner] = timeout_task

    async def _remove_after_timeout(self, runner: discord.Member):
        await asyncio.sleep(2 * 60 * 60)  # 2 hours
        await self.remove_run(runner)

    async def remove_run(self, runner: discord.Member):
        async with self.lock:
            self.active_runs.pop(runner, None)
        async with self.timeouts_lock:
            task = self.timeouts.pop(runner, None)
            if task:
                task.cancel()

    async def reset_timeout(self, runner: discord.Member):
        async with self.timeouts_lock:
            task = self.timeouts.get(runner)
            if task:
                task.cancel()
            timeout_task = asyncio.create_task(self._remove_after_timeout(runner))
            self.timeouts[runner] = timeout_task

    def get_run(self, player: discord.Member) -> Run | None:
        if player in self.active_runs:
            return self.active_runs[player]
        for run in self.active_runs.values():
            if player in run.attendees:
                return run
        return None

    async def get_runner_for_player(self, player: discord.Member) -> discord.Member | None:
        if player in self.active_runs:
            return player
        async with self.lock:
            for runner, run in self.active_runs.items():
                if player in run.attendees:
                    return runner
        return None

    async def is_player_in_run(self, player: discord.Member) -> bool:
        if player in self.active_runs:
            return True
        async with self.lock:
            for run in self.active_runs.values():
                if player in run.attendees:
                    return True
        return False

    async def add_attendee(self, runner: discord.Member, attendee: discord.Member) -> bool:
        async with self.lock:
            run = self.active_runs.get(runner)
            if run and len(run.attendees) < 7 and attendee not in run.attendees:
                run.attendees.append(attendee)
                return True
        return False

    async def remove_attendee(self, runner: discord.Member, attendee: discord.Member) -> bool:
        async with self.lock:
            run = self.active_runs.get(runner)
            if run and attendee in run.attendees:
                run.attendees.remove(attendee)
                return True
        return False

    async def change_runner(self, old_runner: discord.Member, new_runner: discord.Member):
        async with self.lock:
            run = self.active_runs.pop(old_runner, None)
            if run:
                run.runner = new_runner
                if new_runner in run.attendees:
                    run.attendees.remove(new_runner)
                self.active_runs[new_runner] = run
        async with self.timeouts_lock:
            task = self.timeouts.pop(old_runner, None)
            if task:
                task.cancel()
            timeout_task = asyncio.create_task(self._remove_after_timeout(new_runner))
            self.timeouts[new_runner] = timeout_task

    async def increment_run_name(self, runner: discord.Member) -> str | None:
        async with self.lock:
            run = self.active_runs.get(runner)
            if run:
                run_name = run.run_name
                matches = re.findall(r"[0-9]*$", run_name)
                match = matches[0]
                if match == "":
                    run_name += "-1"
                else:
                    new_match = str(int(match) + 1).zfill(len(match))
                    run_name = re.sub(r"[0-9]*$", new_match, run_name)
                run.run_name = run_name
                return run_name
        return None

class JoinRunView(discord.ui.View):
    def __init__(self, runner: discord.Member, timeout=850):
        super().__init__(timeout=timeout)
        self.runner = runner
        self.message = None
        join_button = discord.ui.Button(style=discord.ButtonStyle.green, label="Join Run")
        join_button.callback = self.join_callback
        self.add_item(join_button)

    async def join_callback(self, interaction: discord.Interaction):
        run = run_manager.get_run(self.runner)
        if not run:
            await interaction.response.send_message("The run no longer exists.", ephemeral=True)
            return
        user = interaction.user
        if await run_manager.is_player_in_run(user):
            await interaction.response.send_message("You are already in a run or hosting one.", ephemeral=True)
            return
        if await run_manager.add_attendee(self.runner, user):
            await db.add_attendee(self.runner.id, user.name)
            available_spots = 7 - len(run.attendees)
            game_info_message = f"Game Name: {run.run_name}\nGame Password: {run.password}"
            await interaction.response.send_message(content=game_info_message, ephemeral=True)
            channel = bot.get_channel(run.get_realm())
            if available_spots > 0:
                view = JoinRunView(runner=run.runner, timeout=850)
                message = await channel.send(f"{user.mention} has been added to {run.runner.mention}'s {run.ladder} {run.type} run. There are {available_spots} spots left.", view=view)
                view.message = message
            else:
                await channel.send(f"{user.mention} has been added to {run.runner.mention}'s {run.ladder} {run.type} run. There are {available_spots} spots left.")
        else:
            await interaction.response.send_message("The run is full.", ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
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
        self.run_name = self.children[0].value.strip()
        self.password = self.children[1].value.strip()
        await interaction.response.send_message('Run Info Established!')
        self.stop()

guild_ids = [1106132569914867776]

class RunsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print('Ready!')

    @commands.slash_command(name="dynasty", description="Get a list of the commands for the Runs bot", guild_ids=guild_ids)
    async def dynasty(self, ctx):
        commands_string = '''
These are the commands: /host /ng /runs /end /leave /add /kick /change_runner /advertise /rename /top_runners /top_participants /top_monthly_runners /top_monthly_participants /leaderboard
/host starts a new game with a few options
/broadcast will create a chat message tagging everyone in a game allowing you to send info
/ng creates a new game
/runs will show available and non-available runs with join buttons depending and YOUR game's info if you're joined
/end will close out an instance of a run and is for the host's use
/leave will make you leave a tracked game only if you are a participant
/add will allow you to add someone from the server to your run
/kick will allow you to kick someone from your run except for the host
/change_runner will allow the host to choose a new runner
/advertise will show a join button dialogue in chat for your run
/rename allows you to update your run name and password
/top_hosts and top_participants are self explanatory
/top_monthly_hosts /top_monthly_participants pull the top ten entries respectively from the last 30 days
/leaderboard shows you all relevant stats at once
'''
        await ctx.respond(commands_string, ephemeral=True)

    @commands.slash_command(name="advertise", description="Advertise your game.", guild_ids=guild_ids)
    async def advertise(self, ctx):
        run = run_manager.get_run(ctx.author)
        if run:
            view = JoinRunView(runner=run.runner, timeout=850)
            channel = self.bot.get_channel(run.get_realm())
            message = await channel.send(f"Join {run.type} runs on {run.ladder} hosted by {run.runner.mention}!", view=view)
            view.message = message
        else:
            await ctx.respond("You are not currently in a run.", ephemeral=True)

    @commands.slash_command(name="add", description="Add a player to your game.", guild_ids=guild_ids)
    async def add(self, ctx, player: Option(discord.Member, "Select a player to add.")):
        run = run_manager.get_run(ctx.author)
        if run and run.runner == ctx.author:
            if await run_manager.is_player_in_run(player):
                await ctx.respond(f"{player.mention} is already in a run or hosting one.", ephemeral=True)
                return
            if player == ctx.author:
                await ctx.respond("You can't add yourself to your own run.", ephemeral=True)
                return
            if await run_manager.add_attendee(run.runner, player):
                await db.add_attendee(run.runner.id, player.name)
                await ctx.respond(f"{player.mention} has been added to your run.", ephemeral=True)
            else:
                await ctx.respond("Your run is full.", ephemeral=True)
        else:
            await ctx.respond("Only the host can add players.", ephemeral=True)

    @commands.slash_command(name="rename", description="Change the game name and password of your run.", guild_ids=guild_ids)
    async def rename(self, ctx):
        run = run_manager.get_run(ctx.author)
        if not run or run.runner != ctx.author:
            await ctx.respond("You are not currently hosting a run.", ephemeral=True)
            return
        modal = MyModal(title="Input for run")
        await ctx.send_modal(modal)
        await modal.wait()
        run.run_name = modal.run_name
        run.password = modal.password
        await db.update_run_name(ctx.author.id, modal.run_name)
        channel = self.bot.get_channel(run.get_realm())
        await channel.send(f"{ctx.author.mention}'s game name and password have been updated!")

    @commands.slash_command(name="change_runner", description="Transfer ownership of your run to another player.", guild_ids=guild_ids)
    async def change_runner(self, ctx, new_runner: Option(discord.Member, "Select a new runner.")):
        if ctx.author not in run_manager.active_runs:
            await ctx.respond("You are not currently hosting a run.", ephemeral=True)
            return
        old_runner = ctx.author
        run = run_manager.active_runs[old_runner]
        await run_manager.change_runner(old_runner, new_runner)
        await db.update_runner(old_runner.id, new_runner.id, new_runner.name)
        if new_runner in run.attendees:
            await db.remove_attendee(new_runner.id, new_runner.name)
        channel = self.bot.get_channel(run.get_realm())
        await channel.send(f"{old_runner.mention}'s run has been transferred! {new_runner.mention} is now the new host.")

    @commands.slash_command(name="kick", description="Kick a player from your game.", guild_ids=guild_ids)
    async def kick(self, ctx, player: Option(discord.Member, "Select a player to kick.")):
        run = run_manager.get_run(ctx.author)
        if run and run.runner == ctx.author:
            if player == ctx.author:
                await ctx.respond("You can't kick yourself.", ephemeral=True)
                return
            if await run_manager.remove_attendee(run.runner, player):
                await db.remove_attendee(run.runner.id, player.name)
                await ctx.respond(f"{player.mention} has been kicked from your run.", ephemeral=True)
            else:
                await ctx.respond(f"{player.mention} is not in your run.", ephemeral=True)
        else:
            await ctx.respond("Only the host can kick players.", ephemeral=True)

    @commands.slash_command(name="host", description="Host a new game", guild_ids=guild_ids)
    async def host(self, ctx,
                   ladder: Option(str, "Ladder or non-ladder", choices=["Non-Ladder", "Ladder", "Non-Ladder Hardcore", "Ladder Hardcore"], required=True),
                   run_type: Option(str, "What type of run is this?", choices=["Baal", "Pre-Tele Baal", "Chaos-Full Clear", "Chaos-Seal Pop", "Cows", "Tombs", "Split-Tombs", "TZ", "GRush"], required=True)):
        if await run_manager.is_player_in_run(ctx.author):
            await ctx.respond("You are already hosting or in a run!", ephemeral=True)
            return
        modal = MyModal(title="Input for run")
        await ctx.send_modal(modal)
        await modal.wait()
        run = Run(ctx.author, ladder, run_type, modal.run_name, modal.password)
        await run_manager.add_run(run)
        await db.insert_run(run)
        view = JoinRunView(runner=ctx.author, timeout=850)
        channel = self.bot.get_channel(run.get_realm())
        message = await channel.send(f"**`NEW RUN ALERT!`**\nJoin {run.type} runs on {run.ladder} hosted by {ctx.author.mention}!", view=view)
        view.message = message

    @commands.slash_command(name="end", description="End a run", guild_ids=guild_ids)
    async def end(self, ctx):
        if ctx.author in run_manager.active_runs:
            channel = self.bot.get_channel(run_manager.active_runs[ctx.author].get_realm())
            await run_manager.remove_run(ctx.author)
            await channel.send(f"{ctx.author.mention} has ended the run.")
        else:
            await ctx.respond("You are not hosting a run.", ephemeral=True)

    @commands.slash_command(name="broadcast", description="Send a message tagging all your attendees.", guild_ids=guild_ids)
    async def broadcast(self, ctx, message: str):
        run = run_manager.get_run(ctx.author)
        if run:
            player_list = run.attendees.copy()
            player_list.append(run.runner)
            mention_list = [x.mention for x in player_list]
            await ctx.respond(f"Broadcast to {','.join(mention_list)}\n\n{message}")
        else:
            await ctx.respond("You are not currently in a run.", ephemeral=True)

    @commands.slash_command(name="runs", description="Show current runs.", guild_ids=guild_ids)
    async def runs(self, ctx):
        if not run_manager.active_runs:
            await ctx.respond("There are no current runs.", ephemeral=True)
            return
        message_parts = []
        has_view = False
        view = None
        for runner, run in list(run_manager.active_runs.items()):
            has_available_spots = len(run.attendees) < 7
            if ctx.author in run.attendees or ctx.author == run.runner:
                msg = f"Game Name: {run.run_name}\nGame Password: {run.password}\nRunner: {run.runner.name}\n# {run.ladder}\nType: {run.type}\n"
            else:
                msg = f"Runner: {run.runner.mention}\n# {run.ladder}\nType: {run.type}\n"
            msg += "Attendees:\n"
            for attendee in run.attendees:
                msg += f"{attendee.mention}\n"
            msg += "\n\n"
            message_parts.append(msg)
            if has_available_spots and not has_view:
                view = JoinRunView(runner=runner, timeout=850)
                has_view = True
        full_message = "".join(message_parts)
        if view:
            response = await ctx.respond(full_message, view=view, ephemeral=True)
            view.message = response
        else:
            await ctx.respond(full_message, ephemeral=True)

    @commands.slash_command(name="leave", description="Leave a run.", guild_ids=guild_ids)
    async def leave(self, ctx):
        run = run_manager.get_run(ctx.author)
        if not run:
            await ctx.respond("You are not part of any runs.", ephemeral=True)
            return
        if run.runner == ctx.author:
            await ctx.respond("You are the runner of this game! Use /end to end the game instead.", ephemeral=True)
            return
        await run_manager.remove_attendee(run.runner, ctx.author)
        await db.remove_attendee(run.runner.id, ctx.author.name)
        spots_available = 7 - len(run.attendees)
        view = JoinRunView(runner=run.runner, timeout=850)
        channel = self.bot.get_channel(run.get_realm())
        message = await channel.send(f"{ctx.author.mention} has left the {run.ladder} {run.type} run. There are {spots_available} spots available in {run.runner.mention}'s runs.", view=view)
        view.message = message

    @commands.slash_command(name="ng", description="Increment your run", guild_ids=guild_ids)
    async def ng(self, ctx):
        run = run_manager.get_run(ctx.author)
        if not run:
            await ctx.respond("You are not in a run.", ephemeral=True)
            return
        await run_manager.reset_timeout(run.runner)
        new_name = await run_manager.increment_run_name(run.runner)
        if new_name:
            run.start_time = datetime.datetime.now(datetime.UTC)
            await db.insert_run(run)
            await ctx.respond(f"New run at: {new_name}", ephemeral=True)
        else:
            await ctx.respond("Failed to increment run name.", ephemeral=True)

    @commands.slash_command(name="top_hosts", description="Get top players who hosted the most runs", guild_ids=guild_ids)
    async def top_hosts(self, ctx):
        result = await db.get_top_hosts()
        if not result:
            await ctx.respond("No one has hosted any runs yet.", ephemeral=True)
            return
        message = "**Top Hosts:**\n"
        for index, (runner, total_runs) in enumerate(result, start=1):
            message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"
        await ctx.respond(message, ephemeral=True)

    @commands.slash_command(name="top_monthly_hosts", description="Get top players who hosted the most runs this past month.", guild_ids=guild_ids)
    async def top_monthly_hosts(self, ctx):
        result = await db.get_top_hosts(last_month=True)
        if not result:
            await ctx.respond("No one has hosted any runs yet.", ephemeral=True)
            return
        message = "**Top Hosts for the Last 30 Days:**\n"
        for index, (runner, total_runs) in enumerate(result, start=1):
            message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"
        await ctx.respond(message, ephemeral=True)

    @commands.slash_command(name="top_participants", description="Get top players who participated in the most runs", guild_ids=guild_ids)
    async def top_participants(self, ctx):
        result = await get_top_participants(db)
        if not result:
            await ctx.respond("No one has participated in any runs yet.", ephemeral=True)
            return
        message = "**Top Participants:**\n"
        for index, (participant, count) in enumerate(result, start=1):
            message += f"`{index}. {participant}: Participated in {count} Runs`\n"
        await ctx.respond(message, ephemeral=True)

    @commands.slash_command(name="top_monthly_participants", description="Get top players who participated in the most runs this month", guild_ids=guild_ids)
    async def top_monthly_participants(self, ctx):
        result = await get_top_participants(db, last_month=True)
        if not result:
            await ctx.respond("No one has participated in any runs yet.", ephemeral=True)
            return
        message = "**Top Participants in the Last 30 Days:**\n"
        for index, (participant, count) in enumerate(result, start=1):
            message += f"`{index}. {participant}: Participated in {count} Runs`\n"
        await ctx.respond(message, ephemeral=True)

    @commands.slash_command(name="leaderboard", description="Get top players who participated in/hosted the most runs this month and all-time", guild_ids=guild_ids)
    async def leaderboard(self, ctx):
        monthly_hosts = await db.get_top_hosts(last_month=True)
        all_time_hosts = await db.get_top_hosts()
        monthly_participants = await get_top_participants(db, last_month=True)
        all_time_participants = await get_top_participants(db)
        message = "**Top Hosts for the Last 30 Days:**\n"
        for index, (runner, total_runs) in enumerate(monthly_hosts, start=1):
            message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"
        message += "\n**Top Hosts All-Time:**\n"
        for index, (runner, total_runs) in enumerate(all_time_hosts, start=1):
            message += f"`{index}. {runner}: Hosted {total_runs} Runs`\n"
        message += "\n**Top Participants in the Last 30 Days:**\n"
        for index, (participant, count) in enumerate(monthly_participants, start=1):
            message += f"`{index}. {participant}: Participated in {count} Runs`\n"
        message += "\n**Top Participants All-Time:**\n"
        for index, (participant, count) in enumerate(all_time_participants, start=1):
            message += f"`{index}. {participant}: Participated in {count} Runs`\n"
        await ctx.respond(message, ephemeral=True)

db = Database()
run_manager = RunManager()
TOKEN = "..."
intents = discord.Intents.all()
bot = commands.Bot(intents=intents)
bot.add_cog(RunsCog(bot))
bot.run(TOKEN)
