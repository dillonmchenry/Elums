# Sample tracks

Downloaded Oct 4 2026 for N5's full-song ingest validation
(IMPLEMENTATION_PLAN_2026-10-04.md) — per the plan's approved default
(Oct 3 plan's MA-2), two CC-licensed tracks with a sung lead, so Oct 12's
clean-clone demo stays reproducible without a licensing question. Neither
file is committed to git (`.gitignore` excludes `data/`); re-run the
download commands below on a fresh checkout.

| File | Title | Artist | License | Source | Duration |
| --- | --- | --- | --- | --- | --- |
| `fill-me-up-ellody.mp3` | Fill Me Up | Ellody (!) | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [archive.org/details/FillMeUp-Ellody](https://archive.org/details/FillMeUp-Ellody) | 268.3 s |
| `is-this-all-liz-james.mp3` | Is This All | Liz James | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) | [archive.org/details/IsThisAll](https://archive.org/details/IsThisAll) | 221.3 s |

Re-download:

```powershell
curl.exe -s -L "https://archive.org/download/FillMeUp-Ellody/FillMeUp.mp3" -o data/samples/fill-me-up-ellody.mp3
curl.exe -s -L "https://archive.org/download/IsThisAll/Is%20this%20All" -o data/samples/is-this-all-liz-james.mp3
```

Note the second file's archive.org filename has no `.mp3` extension
(`Is this All`, format `VBR MP3`) — confirmed via `archive.org/metadata/IsThisAll`
directly rather than guessed; the obvious `Is%20this%20All.mp3` URL 404s.
