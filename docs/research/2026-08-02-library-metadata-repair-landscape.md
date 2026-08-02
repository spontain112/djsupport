# Personal library metadata repair: build, buy, or orchestrate?

**Status:** Wayfinder research note, 2026-08-02. No private library was read and
no live service was called.

## Conclusion

Do **not** build a metadata identification/tagging engine. The useful frontier
is a copied-file trial of existing tools, followed—only if it adds value—by a
thin DJ Support suggestion/review/export seam. The leading trials are:

1. **Yate** for inexpensive, Mac-native, scriptable repair spanning DJ stores,
   MusicBrainz/AcoustID and Apple Music integration.
2. **OneTagger** for DJ-store metadata and fill-empty behavior, with an explicit
   maintenance/API-compatibility check because its public changelog currently
   stops at 1.7.0 (2023-08-03).
3. **MusicBrainz Picard** for acoustic-fingerprint recovery when title/artist
   are absent or wrong.
4. **Lexicon** only if direct Rekordbox/Apple Music round-trip, undo and library
   management justify a subscription.

The irreversible boundary is not lookup; it is applying a suggestion. DJ
Support must never turn enrichment into an Approved Match, edit an audio file,
or rewrite Rekordbox/Apple Music without a backup, per-field Preview, and an
explicit user-approved Apply action.

## What the host libraries permit

- Rekordbox can export a collection as XML, and its documented developer bridge
  can display playlists and track information from a supported XML file. Its
  manual also documents **Reload Tag**, which rereads ID3/file tags into the
  Rekordbox library. This supports an export/suggest/tag/reload workflow, not a
  supported public API for arbitrary database mutation. Streaming-track
  information cannot be edited. [Rekordbox developer XML](https://rekordbox.com/en/support/developer/),
  [Rekordbox 7 manual](https://cdn.rekordbox.com/files/20240509141437/rekordbox7.0.0_manual_EN.pdf),
  [Rekordbox 7 FAQ](https://rekordbox.com/en/support/faq/rekordbox7/)
- Apple Music on Mac permits manual and batch editing of song information,
  including artist, title, album, genre and BPM. It exports all Info-window
  fields as text or library/playlist information as XML; playlist re-import
  includes only media already in the library. [Edit song information](https://support.apple.com/guide/music/change-song-and-cd-information-mus2561f46f8/mac),
  [export/import behavior](https://support.apple.com/en-nz/guide/music/-mus27cd5060f/mac)
- MusicKit can search/read a permitted library and add content or create/edit
  playlists, but its documented mutation surface does not expose arbitrary
  local-song tag editing. A DJ Support integration should therefore prefer
  reviewed exports or established desktop automation/tool integration over
  assuming MusicKit can rewrite tags. [MusicKit](https://developer.apple.com/musickit/),
  [MusicLibrary](https://developer.apple.com/documentation/musickit/musiclibrary)

## Tool comparison

| Option | Useful fields and identification | Target and safety | macOS / cost / integration |
|---|---|---|---|
| **Yate** | Broad tag editing; integrations include AcoustID/AcousticBrainz, Beatport, Discogs, MusicBrainz, last.fm and Music/iTunes. Suitable for title, artist, album, date, genre, IDs/art; BPM/key are primarily edit/import fields rather than its core analysis promise. | Audio-file tags; action scripting makes controlled batches possible. Trial only on copies and keep host-library backup. | macOS only; official price $20 perpetual with 14-day trial. Apple Music-aware and scriptable. [Yate](https://2manyrobots.com/yate/) |
| **OneTagger** | Beatport, Traxsource, Juno, Discogs, iTunes, MusicBrainz, Beatsource and Spotify lookup; Shazam identification; includes remixer, label/store metadata, genre/subgenre, date, artwork and ISRC. User selects fields and **overwrite** versus **fill empty**. | Writes audio tags; batch folder/playlist input. Its fill-empty control is a good safety primitive, but not a substitute for copied-file Preview. Network lookup varies by selected source/account. | Free/open-source, macOS Catalina+; source/CLI offer orchestration potential. Public release freshness must be tested. [OneTagger](https://onetagger.github.io/) |
| **MusicBrainz Picard** | Strong title/artist/release/album/date/genre/ISRC/label relationships and artwork; AcoustID/Chromaprint can identify audio with missing or incorrect tags. It is less DJ-store/version oriented than OneTagger/Yate. | Shows proposed metadata and writes only on **Save**; supports batch selection and broad formats. Lookup/fingerprint resolution and artwork use network services. | macOS/Windows/Linux, GPL-2.0-or-later; plugins/scripts are extensible, but embedding GPL code requires license care. [formats and Save behavior](https://picard-docs.musicbrainz.org/en/latest/faq/faq_file_formats.html), [license/development](https://picard.musicbrainz.org/docs/development/), [tag mapping](https://picard-docs.musicbrainz.org/en/latest/appendices/tag_mapping.html) |
| **beets** | MusicBrainz autotagging plus plugins; Chromaprint/AcoustID can identify files with no useful tags; plugins can add sources and fields. | Can keep suggestions in its database without writing (`-W`/`import.write` off); timid mode asks for every decision. Best programmable substrate, but CLI-heavy. Fingerprints stay local unless the user separately submits them; lookup still uses AcoustID. | Cross-platform, MIT; current repository release v2.11.0 (2026-05-06). Strongest open-source integration API. [repository/license](https://github.com/beetbox/beets), [fingerprinting/privacy controls](https://beets.readthedocs.io/en/v2.1.0/plugins/chroma.html), [plugin API](https://beets.readthedocs.io/en/stable/dev/plugins/autotagger.html) |
| **Lexicon** | DJ-library cleanup, missing tags/art, Track Matcher, custom fields and file-tag writing; Rekordbox 5/6/7 and Music/iTunes import/sync. Covers broad descriptive fields; its strength is library workflow rather than an open identification engine. | Native library conversion/sync, Undo History, archive and database/cloud backup. Still require an external Rekordbox backup and a synthetic/copied-library trial. | macOS/Windows; free conversion tier and paid library-management subscriptions (current amounts are dynamically presented). Local plugins/API are a possible integration, subject to tier and contract. [manual](https://www.lexicondj.com/manual/all), [pricing](https://www.lexicondj.com/pricing) |
| **Mp3tag / Metadatics** | Excellent manual/batch tag editing, online Discogs/MusicBrainz-style lookup, artwork and transformations; no official acoustic-fingerprint claim found. | Audio tags, with previews/manual release alignment; host libraries must refresh/reimport. | Commercial Mac apps; useful buy-only comparators, not obvious DJ Support integration substrates. [Mp3tag](https://mp3tag.app/), [Metadatics](https://www.markvapps.com/metadatics) |
| **Mixed In Key** | Best treated as complementary audio analysis for BPM, key and energy, plus cue points—not broad identity/label/ISRC recovery. | Writes analysis/tag data and documents Rekordbox XML/reload-tag workflow. | Commercial Mac/Windows desktop workflow; no reason to use it as the general metadata engine. [Rekordbox workflow](https://mixedinkey.com/workflows/use-mixed-in-key-with-rekordbox/), [integration overview](https://mixedinkey.com/integration/introduction/) |

No single source is authoritative for every field. In particular, “mix” naming,
genre and original release date are policy choices; BPM/key can be measured but
may differ by analyzer; artwork and label/release attribution are edition
specific; and ISRC is useful evidence, not guaranteed unique identity.

## Build versus buy

| Path | Judgment |
|---|---|
| Configure/buy an existing tool | **First.** Fastest evidence and already covers tagging, lookup and review. Run Yate, OneTagger and Picard against a tiny synthetic/copied set containing deliberate gaps; add Lexicon only to test native round-trip/undo. |
| Build a thin DJ Support orchestrator/export | **Possible later.** Valuable only if it unifies source provenance, presents per-field alternatives/confidence, emits a reviewable sidecar/CSV, and delegates applying changes to a proven tool or an explicit narrow adapter. beets has the cleanest open plugin substrate; OneTagger has the closest DJ-store semantics. |
| Build a full metadata engine | **Reject.** It duplicates fingerprinting, catalog normalization, format-specific tag writers, artwork handling and continuously changing provider adapters, while creating the highest corruption/privacy risk. |

## Safe validation protocol

Use only synthetic files or user-created copies. Before any real trial, export
the Apple Music/Rekordbox library and back up the selected audio files. Compare
per field: old value, proposed value, source, release/version, confidence and
whether the value is missing versus conflicting. Default to suggestion-only;
Apply must name its target (file tags, Rekordbox refresh/export, or Music
library), recheck the file/library head, and produce a reversible audit record.
Never scan directories or submit fingerprints without explicit authorization.

## Relationship to existing work

- [Evaluate recovery of missing and noisy source metadata](https://github.com/spontain112/djsupport/issues/32)
  remains the umbrella; this note adds a separate **library repair** branch,
  rather than changing lossless Transfer source intake.
- [Evaluate ISRC-first matching from source metadata](https://github.com/spontain112/djsupport/issues/31)
  remains matching research. A recovered ISRC can be presented as sourced
  evidence, but cannot itself approve a match or authorize a library edit.
- [Prototype: measure privacy-preserving ISRC feasibility and API cost](https://github.com/spontain112/djsupport/issues/42)
  remains the bounded evidence gate. Any local-file or live phase still needs
  separate consent; this tool trial does not bypass it.

## Wayfinder disposition

Put **full metadata engine** in the fog/rejected branch. Put **copied-file tool
bake-off** on the near decision frontier. A successful bake-off may yield one
narrow ticket for a suggestion artifact or tool handoff; it must not yield a
general-purpose library writer by implication.

**Next one-at-a-time question:** Which missing field causes you the most pain
today: artist/title/version, label/date/genre, ISRC, artwork, or BPM/key?
