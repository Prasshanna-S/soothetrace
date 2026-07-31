# Record pages: what History and the profile page must do

The design contract for the two record surfaces of the care console. The renderers in
web/app.js and the closing sections of web/app.css implement it; changes to either should
keep every rule below true.

## History

Purpose: a caregiver looks back and answers one question fast: what was tried, and did it
help. Everything on the page serves that question.

Structure, top to bottom:

1. Header: profile name as the kicker, History as the title, a one-line count status.
2. Day group labels: Today, Yesterday, then full dates. Uppercase, quiet, no box.
3. The newest moment renders as the page hero: the same pastel mega-card grammar as the
   Listen suggestion card, with display-size title, the action object large at the right,
   and white chips. A synthetic newest moment takes the blush variant. Every later moment
   is a compact floating row.
4. One soft card per recorded moment:
   - the action object floats free at the left, no tile, no border behind it;
   - the action phrase is the title and never truncates into ellipsis;
   - ONE meta line: time, duration, then the outcome as a worded state
     (Helped in green, Not yet in grey, No outcome in faint). Never prose like
     "Outcome not recorded" repeated per row;
   - a badge appears only when it carries information the row does not:
     seeded (red-tinted) and inferred (periwinkle). Caregiver-sourced rows carry
     no badge, because that is the default the reader assumes;
   - the caregiver's outcome sentence appears only when it says something beyond
     the worded state;
   - tags render as small chips under the row, never as floating text;
   - a chevron marks the row as openable.
4. Show earlier moments: one ghost pill, driven by the server cursor.
5. States: loading skeletons, an honest error with retry, an empty state with copy that
   explains what will appear. Nothing is ever invented to fill space.

The detail view keeps the four tabs (Overview, Said, Context, Evidence) with the dark
active tab. The hero card holds the action, outcome sentence, worded state and provenance
badges, and the action object in a soft disc. Recorded speech and typed follow-up stay
visually distinct. Quotes are literal or absent.

## Profile (Baby)

Purpose: who this profile is and how ready its memory is.

1. Header: name and a status pill (ready in mint, anything else in butter).
2. The memory hero: one large count, the readiness sentence, progress beads, and the
   profile object floating at the right. This is the only colored surface on the page.
3. Training clips: one contained card with flat divider rows (ordinal disc, Clip n,
   time and duration, playback when available). Never a card inside a card.
4. Memory signals: quiet chips naming what the profile has recorded. No values, no
   scores, no percentages.
5. States: loading skeletons, honest error with retry, empty copy for zero clips.

## Both pages

- No similarity bands, scores, or confidence numbers anywhere.
- Synthetic data is impossible to miss but never shouts twice: a tinted border plus one
  badge, not repeated prose.
- Cards float on soft shadow, never on hairline borders; radius 22 and up.
- The pages compose for portrait and short landscape; the History hero spans the full
  width in landscape and nothing scrolls horizontally.
- The sticker-wall background stays at whisper opacity and never competes with content.
