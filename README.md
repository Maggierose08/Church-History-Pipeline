# Church History Video Pipeline

Automated pipeline telling real, documented church history stories in full - early
Christianity, church fathers, missionary movements, councils, persecutions, and
notable figures across all eras and regions. Unlike the other pipelines in this
family, this one uses **procedurally-drawn stick-figure illustrations** (colored
robes, background landmarks, simple props) instead of stock/gameplay footage, and
posts each story as a **series of 1-1.5 minute segments first, followed by a full
10-minute compilation 3 days later** - all sharing the same 3-posts-per-day budget.
YouTube only, no Facebook.

## How this pipeline differs from the others in this family

- **Search-grounded content**: uses Gemini's Google Search grounding tool to verify
  historical accuracy rather than relying on the model's training data alone (free:
  5,000 grounded prompts/month, far more than this pipeline's real usage)
- **Topic history tracking**: keeps a running list of every specific historical event
  already covered, injected into future prompts as a "do not repeat" list - avoiding
  the same event being told twice, distinct from the small local fallback pool
- **Variable-length series**: 7-9 short segments per story (not a fixed 3), each with
  its own visual scenes, followed by a compiled full-length video
- **A pending-compilations queue**: when a track finishes all its segments, the full
  compilation is queued for 3 days later, and the track immediately starts a new
  story - the compilation isn't tied to any specific track once queued, and competes
  for the same daily slots as ongoing short-form content
- **Procedural stick-figure rendering**: no stock footage, no AI image generation for
  visuals (both cost/quota concerns at this content's scale) - `stick_figures.py`
  draws simple colored-robe figures with background landmarks and props using pure
  Pillow drawing code, then `kenburns.py` applies a slow pan/zoom effect via ffmpeg's
  zoompan filter, all at zero API cost

## Content longevity

Real church history spans ~2,000 years across every inhabited continent - even
conservatively, this domain supports many hundreds to low thousands of distinct
tellable stories. At this pipeline's consumption rate (roughly 1 new story needed
every 2.5-3 days across 3 parallel tracks), a pool of even 300 distinct events would
last over 2 years before any repeat; 1,000+ would last 7+ years. The real constraint
isn't running out of material - it's avoiding accidental repetition, which the topic
history system handles directly.

## Local fallback stories included

5 fully-written, validated stories (7 segments each, 35 segments total), used only
when Gemini/Search both fail:
- `story_01.json` - The martyrdom of Perpetua and Felicity, Carthage, 203 AD
- `story_02.json` - Saint Patrick's enslavement and voluntary return to Ireland
- `story_03.json` - The Council of Nicaea and the Arian controversy, 325 AD
- `story_04.json` - The martyrdom of Polycarp, bishop of Smyrna, c. 155 AD
- `story_05.json` - Ignatius of Antioch's journey to martyrdom and his surviving letters

The local fallback pool preferentially picks stories that have never been told before
(checked against the same topic history the AI-generation path uses), only allowing a
repeat once the entire pool has genuinely been exhausted.

## Visual style customization

`stick_figures.py` supports 7 poses (walking, standing, sitting, kneeling, praying,
teaching, pointing), 6 robe colors, 5 sky backgrounds, 4 background landmarks (temple,
hills, ship, wall), and 3 props (staff, scroll, cross). The `church_script.py` prompt
constrains Gemini to only select from these exact values - extending the visual
library (new poses/colors/landmarks) requires updating both `stick_figures.py` and the
valid-values lists in `church_script.py` together.

## Setup

Same secrets pattern as the other pipelines: `GEMINI_API_KEY`, `GCS_BUCKET`,
`GCS_SERVICE_ACCOUNT_JSON` (also authenticates Cloud Text-to-Speech), and a YouTube
channel's `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`/`YOUTUBE_REFRESH_TOKEN` - see the
accompanying reference document for the full OAuth walkthrough. No Pexels key needed
(no stock footage), no Facebook secrets needed.

## Still needed before going live

- New GitHub repo
- New YouTube channel + refresh token (verify the channel via `channels?mine=true`
  before saving)
- Enable Cloud Text-to-Speech API on your Google Cloud project
