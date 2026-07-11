# Generate a QOTD Question for a Topic

Generate one multiple-choice Question of the Day candidate from the supplied topic and evidence. The final trivia question may be adjacent to the timely or curated hook, but its answer must be supported by the supplied source material.

## Assignment

- Category: {{ category }}
- Topic title: {{ topic.title }}
- Topic summary: {{ topic.summary }}

## Retrieved evidence

{% for item in evidence -%}
### Source {{ loop.index }}

- Title: {{ item.title }}
- URL: {{ item.url }}
- Evidence: {{ item.snippet }}

{% else -%}
No source evidence was supplied. Do not generate a question.
{% endfor %}

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
- Let the sender's personality remain visible. When the fact would otherwise sound dry, include one brief personal reaction, audience-directed comment, or playful parenthetical. Keep it natural, readable, and limited to one aside.
- Slightly casual phrasing is welcome, but do not deliberately add spelling or factual errors and do not become incoherent.
- Prefer surprising, oddly specific facts from broadly approachable subjects such as geography, pop culture, sports, holidays, records, brands, or school-adjacent knowledge.
- Aim for accessible-to-moderate difficulty: interesting to guess without requiring obscure expert knowledge.
- Use the provided category as the broad trivia category.

## Answers and evidence

- Return exactly four distinct options labeled A, B, C, and D.
- Make the options parallel, concise, plausible, and non-overlapping. At most one may be knowingly silly when that suits the question.
- Ensure exactly one option is correct and that the supplied source evidence supports that answer.
- Include source metadata that identifies the evidence used.
- Do not reveal or strongly hint at the correct option in the question wording.

## Safety and quality

- Use a stable, verifiable fact.
- Avoid grim, partisan, medical, legal, or highly volatile subjects.
- Avoid obscure facts that only a specialist could reasonably answer.
- Do not turn a sensitive current event, tragedy, health concern, or legal dispute into entertainment.
- Do not invent facts, citations, or source support.

## Output

Return only structured JSON matching the requested schema. Do not include markdown, commentary, or extra keys.
