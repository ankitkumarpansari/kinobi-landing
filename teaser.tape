# Teaser GIF — stealth launch
Output teaser.gif
Output teaser.mp4

Set Shell "bash"
Set FontSize 16
Set Width 1400
Set Height 780
Set Padding 24
Set FontFamily "JetBrains Mono"
Set Theme "Builtin Dark"
Set TypingSpeed 35ms
Set CursorBlink true

# Setup: run fast, then clear
Type "export PATH='/Users/ankitpansari/Desktop/kinobi-landing/demo-bin:$PATH' && export PS1='→ ' && clear"
Enter

Sleep 1s

# Act 1: Set the scene
Type "# what if your AI agent could do sales research?"
Enter
Sleep 2s

Type "# let's find warm paths into a target account."
Enter
Sleep 2s

# Act 2: Search
Type@70ms '_____ search --query "series B+ fintech, hiring CX leader, using Zendesk"'
Enter
Sleep 5s

# Act 3: Enrich
Type@70ms "_____ enrich ramp.com --depth full"
Enter
Sleep 5s

# Act 4: Agent reasoning
Type@70ms '_____ agent --task "analyze ramp and draft approach strategy"'
Enter
Sleep 8s

# Act 5: The tease
Type ""
Enter
Sleep 1s
Type@150ms "# coming soon."
Enter
Sleep 4s
