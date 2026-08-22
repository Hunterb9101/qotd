# Rewrite an Answer-Leaking QOTD Prompt

Rewrite the failed Player-facing prompt below. The correct answer is provided only so you can
avoid it; players will not see the answer, options, or source material.

## Failed candidate

- Category: {{ category }}
- Topic: {{ topic }}
- Player-facing prompt: {{ question.prompt }}
- Correct answer (private): {{ question.correct_answer }}

### Options (private)

{% for label, option in question.options.items() -%}
- {{ label }}: {{ option }}
{% endfor %}

### Source evidence (private)

{% for source in sources -%}
- URL: {{ source.url }}
  Evidence: {{ source.evidence }}
{% endfor %}

## Required rewrite

- Ask about the same underlying fact.
- The following text is forbidden in the Player-facing prompt: `{{ question.correct_answer }}`.
- Keep the prompt answer-neutral: do not name the correct answer or use a brand, product, person,
  place, title, or other identifier that refers or alludes to it.
- Do not mention the source, its publisher, or its URL in the Player-facing prompt.
- Do not reuse the failed Player-facing prompt.
- Before returning, verify that the Player-facing prompt contains no case-insensitive occurrence
  of the forbidden text and no identifier associated with that answer.

## Output

Return only the replacement Player-facing prompt in the requested structured field.
