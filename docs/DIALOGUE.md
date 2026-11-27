# Dialogue: every line, in the order the scripts play it

Episode III keeps a scene's text inside its script (`cf\us\NNNN.sb`,
`bat\us\*.sb`): one pool of strings per file, and a program that hands them
to the engine. `dialogue` reads the program and writes the lines it shows, in
the order its code shows them:

```sh
python cli.py dialogue --iso "Disc 1.iso" --iso "Disc 2.iso" --out lines/            # text, ~15 s
python cli.py dialogue --iso "Disc 1.iso" --iso "Disc 2.iso" --out lines/ --voice    # + one WAV per voiced line
python cli.py dialogue --iso "Disc 1.iso" --out lines/ --only 8000                   # one scene
python cli.py sb --iso "Disc 1.iso" --path "cf\us\8000.sb"                    # the program itself
python cli.py natives --iso "Disc 1.iso" --iso "Disc 2.iso" --out natives/    # what the scripts call
```

`text-export` stays the tool for *editing*: it writes each pool whole, in pool
order, the developers' debug prints among the lines. `dialogue` is the tool
for *reading and listening*: only what reaches the screen, with speakers,
choices, branches, each event line's voice clip, and the subtitles of the
movies and event scenes a script starts. Every row keeps its pool number (`[#0114]`), which is the
`### 0114` block of that scene in `text-export`'s tree.

It works on the USA discs, the May 2006 prototype and the Japanese discs
(the script machine is the same in all of them; [FORMATS.md](FORMATS.md)
section 7).

## What comes out

| Path | What |
|---|---|
| `scripts/cf/<scene>.txt` | a play-script transcript per scene script |
| `scripts/bat/<name>.txt` | the same per battle script |
| `voice/<scene>/NNNN_<who>_<id>.wav` | `--voice`: one clip per voiced line, the line's own stream decoded by ffmpeg |
| `dialogue.csv` | every row: `source, scene, order, entry, branch, kind, speaker, text, text_id, native, voice, voice_path, time, clip, pc, raw, path` |

Counts (2026-11-21, both discs of each build given):

| Build | Scripts | With lines | Rows | Event lines | Boxes | Townspeople | Choices | Movie cues | Event-scene cues |
|---|---|---|---|---|---|---|---|---|---|
| USA | 715 | 676 | 15,168 | 4,766 | 2,405 | 2,214 | 1,697 | 1,435 | 1,324 |
| Japan | 856 | 815 | 18,724 | 5,124 | 3,121 | 4,279 | 2,137 | 1,046 | 1,005 |

The May 2006 prototype exports the same way (715 scripts, 676 with lines).

A transcript reads like this (`cf/8000`, the opening):

```
== evt01 ==
  Blue Testament: Looks like things are going smoothly.  [#0114]  <s000200_01vir>
  Blue Testament: Tch. You're as friendly as ever.  [#0116]  <s000200_02vir>
  Red Testament: We must correct the errors.  [#0124]  <s000200_04_2kev>
```

and a field script with a choice and a branch (`objx_M_ptChMode`, in most
field scripts):

```
== objx_M_ptChMode ==
  if:
    (narration) Board the E.S.?  [#0001]
    CHOICE: Yes | No  [#0002]
  else:
    (narration) Disembark the E.S.?  [#0003]
    CHOICE: Yes | No  [#0002]
```

`== name ==` is a routine: one of the script's named entry points (the names
are in the file). `main` comes first, the others in code order. Branches are
kept, not flattened: `if` / `else` / `loop` / `case N` as the compiler laid
the code out. The conditions are flags and are not named. `<...>` after an
event line is its voice id.

A script that starts a movie shows the movie's subtitles in place (`cf/7005`):

```
== main ==
  ~ movie s000300 (runtime.mpeg2) -> mov\s000300.sfd
    [00:23:05] Miyuki!
    [00:24:10] You didn't tell me that they had macrophages deployed!
    [00:27:23] What the hell have you been doing?
```

The times are the subtitle file's own stamps, copied as written.

## Which strings are lines

A string is a line when the code passes it to a function that draws text.
Those functions ("natives") are registered by the engine under a class and a
name, both stored in the executable, and each script lists the ones it
imports, so nothing here is guessed from the shape of a string. On USA Disc 1
the scripts make 550,358 native calls; `sbvm.native_calls` recovers the
argument list of every one.

| Native | Kind in the CSV | Text argument | Calls (USA) |
|---|---|---|---|
| `talk.EvtMsg` | `event` | 4th; the 3rd is the voice id | 4,766 with text |
| `talk.Msg` | `box` | 1st | 2,403 |
| `extalk.Msg` | `npc` | 2nd | 2,214 |
| `talk.Sel` | `choice` | 1st; options split by `\n` | 1,696 |
| `talk.Think` | `think` | 1st | 28 |
| `talk.Sys` | `system` | 1st | 11 |
| `bat.msgOpen` | `battle` | 3rd | 136 |
| `robo.msgOpen` | `battle` | 3rd | 48 |
| `robo.dispSkillName` | `banner` | 2nd | 46 |
| `extalk.KeyWait` | `keyword` | 1st | 576 |

The handlers were read for `talk.Msg`, `talk.Think`, `talk.Sys`, `talk.Sel`,
`talk.EvtMsg`, `extalk.Msg` and `extalk.KeyWait` (USA SLUS `FUN_0026be60`,
`0026bf60`, `0026c018`, `0026c0d0`, `0026c1a8`, `0026bac8`, `0026bc50`): each
takes the argument above through `FUN_001d4238`, the text pool accessor. The
battle natives (`bat`, `robo`, in OV02.OVL) are listed by what their strings
are; their handlers were not read.

**Keywords.** `extalk.KeyWait("not ready")` is not a line. A townsperson's
line marks a word with a `<k...>` tag (`It seems you are <knot ready> yet.`)
and the script then waits for that keyword by its text. In 576 of 576 calls on
the USA discs (1,127 of 1,127 on Japan) the argument is exactly the body of a
`<k...>` tag in the same script. A translation has to change both the same
way; the transcript prints `(waits for the keyword: not ready)` next to the
line so the pair is visible.

**Markers and their files.** Calls that name a resource are kept, and the
name is looked up on the disc. Checked against the indexes of USA Disc 1 and
2 together:

| Native | The id is | Files | Found (USA) |
|---|---|---|---|
| `talk.EvtMsg` (3rd argument) | the line's voice clip | `snd\adx\mev\<id>.adx` | 4,738 of 4,738 |
| `runtime.mpeg2` | a movie | `mov\<id>.sfd`, subtitles `mov\us\<id>.txt` | 36 of 36 movies, 29 with subtitles |
| `runtime.event` | an event scene | `evt\<id>.xep`, audio `snd\adx\evt\<id>.adx`, subtitles `evt\us\<id>.txt` | 67 of 67, 53 with subtitles |
| `bat.caption` | a voiced battle caption | `snd\adx\bat_voice\<id>.adx`, text `mov\us\bat\<id>.txt` | 60 of 60 |
| `bat.adxPlay` | a battle voice clip | `snd\adx\<id>.adx` | 2 of 2 |
| `sound.adxLoad` | a stream | `snd\adx\mev\<id>.adx` | 192 of 192 named |

On the Japanese discs 5,095 of 5,096 voice ids have their stream (the one
without is `s024300_11jul`). 28 event lines on either build name no voice.

So Episode III stores **one voice stream per event line**. That is why
`--voice` needs no cutting or alignment, unlike the Episode II kit: each WAV
is the whole of the line's own file (24,000 Hz mono in the samples checked).
A movie's or event scene's dialogue is in its subtitle file and is listed cue
by cue under the marker; their audio is one track per movie or scene and is
not split into lines.

**Tables.** Three USA scripts (four on Japan) pass a show native a string
taken from a variable: a table of string numbers in the script's globals, or
a message from another thread. The call is printed as `(text from a
variable)` and the table's strings are listed at the end of the transcript
under `strings read through a table`. Which entry a call picks is decided
while the game runs.

## What is not a line

`deb.put` is the developers' debug print. It takes 227,240 of the 245,984
text arguments on USA Disc 1: every `--- main ---`, every Japanese note. So
the pool is mostly not dialogue, and the code says which part is.

`text-export` sorts a pool's strings by their shape (`sb.classify`). Against
the code, on USA Disc 1 (90,580 strings):

| | Strings |
|---|---|
| shape says dialogue (`dialogue` + `untranslated`) | 14,161 |
| ... and a show native draws it | 9,974 |
| ... read through a table | 45 |
| ... only ever passed to `deb.put` (`--- main ---`, `--- Battle Start ---`) | 3,797 |
| ... a keyword for `extalk.KeyWait` | 330 |
| ... empty strings and four ids with a Japanese digit | 13 |
| ... a voice path for `bat.adxPlay` | 2 |
| a show native draws it, but its shape says otherwise | 0 |

So every line the game shows is in `text-export`'s `dialogue` blocks, and
about 3,800 blocks there are debug prints that never reach the screen.
Translating them does no harm and does nothing.

On the Japanese discs the shape rule is weaker, because a Japanese line
without a `[Speaker]` tag looks like a note: of 88,703 strings exported as
`text`, 3,054 are drawn by a show native and 85,649 are not. `dialogue` and
`dialogue.string_kinds(data)` tell them apart.

`string_kinds` gives, for one script, what the code does with each string:
a show kind, `keyword`, `table`, `debug`, `resource` or `unused`. It is there
for tools; `text-export` does not use it yet.

## What is not here

- **Timings of event lines.** Episode II's event lines carry start and end
  frames as arguments. Episode III's `talk.EvtMsg` does not: its two leading
  numbers and two trailing ones were not identified, so an event line has a
  voice clip but no time.
- **Per-line audio for movies and event scenes.** Their subtitle cues have
  times, and their audio is one track; nothing here cuts it.
- **Scene order.** Transcripts are per script. The order in which the game
  runs the scripts (which scene follows which) is story data outside them.
- **Battle natives' handlers** (`bat`, `robo`, OV02.OVL) were not read; their
  rows are listed by what their strings are.

Modules: `dialogue.py`, `sbvm.py`, `sbnatives.py`, `sb.py`.
