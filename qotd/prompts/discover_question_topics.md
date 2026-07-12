# Discover Timely QOTD Topics

Use web search to propose up to {{ limit }} volatile, timely creative directions that could anchor an approachable multiple-choice Question of the Day.

## Editorial brief

{{ brief }}

## What counts as a topic

A topic must be a recognizable entity or named concept, such as a person, place, food, tradition, game, movie, character, team, product, event, holiday, organization, object, or phrase. Write a clean topic title; do not use an article headline as the title.

For each direction, return:

- `title`: the concrete entity or named concept;
- `summary`: a concise explanation of the timely hook and a promising direction for later trivia research.

This is brainstorming, not question research. Do not find, cite, or attribute the final trivia fact here. The downstream question generator will perform its own web search and source the correct answer.

## Timely discovery lanes

Search across these lanes and use whichever naturally fit the assigned category, subject lens, and story angle:

1. **Approachable current events:** Find a concrete person, place, organization, product, discovery, competition, or cultural event appearing in recent news. The current development can be volatile because it is only a diversity hook.
2. **Named food days and observances:** Look for international, national, promotional, or self-proclaimed food days connected to the date. A playful or unofficial observance is acceptable at this brainstorming stage.
3. **New entertainment releases:** Look for recently released or imminently releasing video games, movies, television series, books, or music. Use the release to point toward a title, creator, character, franchise, technology, adaptation, or cultural influence.
4. **Evergreen fallback:** When no timely hook fits naturally, choose an interesting stable entity that strongly matches the category and lenses.

## Selection standards

- Prefer broadly recognizable entities with a surprising, playful, or oddly specific fact behind them.
- Diversify the proposed entities; do not return several versions of the same story.
- Avoid partisan politics, tragedy, active legal disputes, medical advice, rumors, and spoilers.
- Volatile details are allowed in the direction, but the direction must tell the downstream generator to use them only as a hook and research a stable answerable fact.
- Do not invent an entity, release, event, or observance.

Return only structured JSON matching the requested schema.
