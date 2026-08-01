# Repair a Generated QOTD Question

Revise the candidate only enough to correct the listed issues. Most of the question is already
useful, so preserve its category, topic, underlying fact, source evidence, difficulty, and any
wording or answer choices that do not contribute to a reported problem.

## Candidate

- Category: {{ category }}
- Topic: {{ topic }}
- Prompt: {{ question.prompt }}
- Correct option: {{ question.correct_option }}
- Correct answer: {{ question.correct_answer }}
- Source note: {{ question.source_note }}

### Options

{% for label, option in question.options.items() -%}
- {{ label }}: {{ option }}
{% endfor %}

### Source evidence

{% for source in sources -%}
- URL: {{ source.url }}
  Evidence: {{ source.evidence }}
{% endfor %}

## Issues to repair

{% for issue in issues -%}
- {{ issue }}
{% endfor %}

## Repair rules

- Correct every listed issue, but do not replace the topic or choose a new category.
- Keep the same sourced fact and correct answer unless a listed issue says the evidence does not
  support it. In that case, repair the question using only a fact supported by the supplied evidence.
- Retain valid wording and options when possible. Prefer a small editorial correction over a rewrite.
- Keep exactly four distinct options labeled A, B, C, and D with exactly one unambiguous answer.
- Do not add, replace, or invent sources. The supplied URLs and evidence remain authoritative.
- Do not expose or strongly hint at the correct answer in the participant-facing prompt.
- Return only the repaired structured fields. Do not include markdown, commentary, or extra keys.
