# runs_bot
This is the current code for the Runs/Dynasty bot that runs on the TLD Discord server
This is by no means perfect code and was slapped together in my free time.

This bot uses py-cord: pip3 install py-cord

Just add your discord token and your guild id to the code, setup your discord bot for use with slash commands, all intents, and bot permissions, and you just need to run the main file. Voila

These are the discord commands: /host /ng /runs /end /leave /add /kick /change_runner /rename /top_runners /top_participants /top_monthly_runners /top_monthly_participants /leaderboard

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
