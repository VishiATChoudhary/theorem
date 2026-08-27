# vhs tape: theorem REPL demo. Regenerate: vhs demo/demo.tape
Output docs/assets/demo.gif
Set FontSize 17
Set Width 900
Set Height 560
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Padding 16

Hide
Type "uv run python -m theorem --repl --db /tmp/theorem-demo-db"
Enter
Sleep 1.5s
Show

Sleep 800ms
Type "find product where lunch_year > 2024 as recent"
Enter
Type "return recent.name"
Enter
Enter
Sleep 2.5s

Type "find product where launch_year > 2024 as recent"
Enter
Type "follow recent uses component as parts"
Enter
Type "follow parts supplied_by source as sups"
Enter
Type "group by sups as g"
Enter
Type "count distinct g.parts as n_parts"
Enter
Type "return sups.name, n_parts order by n_parts desc budget 2000 tokens"
Enter
Enter
Sleep 4s
