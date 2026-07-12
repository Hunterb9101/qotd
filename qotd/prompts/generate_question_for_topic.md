# Generate a QOTD Question for a Topic

Generate one multiple-choice Question of the Day candidate from the supplied topic. The final trivia question may be adjacent to the timely or curated hook, but its answer must be supported by retrieved source material.

## Assignment

- Category: {{ category }}
- Topic title: {{ topic.title }}
- Topic summary: {{ topic.summary }}
{% if lenses %}
- Subject lens: {{ lenses[0] }}
- Story angle: {{ lenses[1] }}

Use the subject lens to choose the human, cultural, or practical part of the topic to explore. Use the story angle to choose what makes the fact memorable. Combine them naturally as creative directions, not rigid filters, and deviate only when credible research is weak.
{% endif %}

The topic is a research anchor, not necessarily wording that must appear in the question. It may itself be the correct answer when that creates a natural, interesting question. If so, do not name the topic in the question or otherwise reveal or strongly hint at that answer.

## Retrieved evidence

{% if evidence %}
{% for item in evidence -%}
### Source {{ loop.index }}

- Title: {{ item.title }}
- URL: {{ item.url }}
- Evidence: {{ item.snippet }}

{% endfor %}
{% else -%}
No source evidence was supplied. Use web search to research the topic before generating a question. Prefer primary or authoritative sources and base the answer only on information you found.
{% endif %}

{% if prior_rejection_reasons %}
## Prior rejected attempts

Correct every issue below in the new candidate:

{% for reason in prior_rejection_reasons -%}
- {{ reason }}
{% endfor %}
{% endif %}

## Voice and structure

- Ask one short, direct, answerable fact-recall question, optionally preceded by a brief setup.
- Sound informal, conversational, and human: prioritize fun over polished trivia-company prose.
- Lead with what is surprising, strange, or amusing about the fact instead of describing the source or institution that contains it.
- Rewrite academic, institutional, encyclopedic, or promotional source language in ordinary everyday words. Do not sound like a research summary, library catalog, press release, or trivia-company database.
- Ask the question the way a curious friend would ask it aloud. Prefer familiar words and short sentences; avoid legalese, bureaucratic phrasing, formal definitions, and stacked qualifying clauses.
- A law, regulation, court decision, or official policy may support an otherwise fun fact, but describe its practical effect in plain language. Do not mention statute numbers, code sections, formal case names, or procedural jargon unless the name itself is the fact being tested.
- Let the sender's personality remain visible. When the fact would otherwise sound dry, include one brief personal reaction, audience-directed comment, or playful parenthetical. Keep it natural, readable, and limited to one aside.
- Slightly casual phrasing is welcome, but do not deliberately add spelling or factual errors and do not become incoherent.
- Prefer surprising, oddly specific facts from broadly approachable subjects such as geography, pop culture, sports, holidays, records, brands, or school-adjacent knowledge.
- Look beyond introductory and commonly repeated trivia. Do not default to first, earliest, oldest, largest, most expensive, or who-invented-it facts unless the specific story is unusually compelling.
- Aim for accessible-to-moderate difficulty: interesting to guess without requiring obscure expert knowledge.
- Use the provided category as the broad trivia category.

## Answers and evidence

- Return exactly four distinct options labeled A, B, C, and D.
- Research and source only the fact needed to establish the correct answer. Do not treat other names, examples, foods, places, dates, or facts near it in the source as a distractor pool.
- Identify the correct answer's semantic type before writing the options, such as person, place, venue, food, event, year, measurement, object, or process.
- Invent three plausible but incorrect distractors of that same semantic type. Distractors do not need source support and must not be additional answers or claims taken from the cited material.
- Make all four options grammatically parallel, concise, non-overlapping, and independently plausible. At most one may be knowingly silly when that suits the question.
- Ensure exactly one option is correct and answers the literal wording of the question. The retrieved source evidence must support only that correct answer among the four options.
- Include each source URL and a narrowly focused supporting evidence excerpt that establishes the correct answer without presenting a distractor as another plausible answer.
- Do not reveal or strongly hint at the correct option in the question wording.

## Safety and quality

- Use a stable, verifiable fact.
- Avoid grim, partisan, medical, legal, or highly volatile subjects.
- Avoid obscure facts that only a specialist could reasonably answer.
- Do not turn a sensitive current event, tragedy, health concern, or legal dispute into entertainment.
- Do not invent facts, citations, or source support.

## Output

Return only structured JSON matching the requested schema. Do not include markdown, commentary, or extra keys.
