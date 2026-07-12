# Evaluate a Generated QOTD Question

Review the multiple-choice trivia question below as a strict but practical editor. The correct answer is intentionally visible to you for evaluation and must not be exposed to players.

## Candidate

- Category: {{ category }}
- Topic: {{ topic }}
- Prompt: {{ question.prompt }}
- Correct option: {{ question.correct_option }}
- Correct answer: {{ question.correct_answer }}

### Options

{% for label, option in question.options.items() -%}
- {{ label }}: {{ option }}
{% endfor %}

### Supporting material

- Source note: {{ source_note }}
{% for evidence in source_evidence -%}
- Evidence: {{ evidence }}
{% endfor %}

## Review criteria

Reject the candidate when any of these are true:

- The prompt states the correct answer, contains a close paraphrase of it, or effectively defines it so completely that no real recall or inference remains.
- The wording, grammar, level of detail, or semantic type of the options points conspicuously to the correct choice.
- More than one option reasonably answers the literal question.
- The options are repeated, overlapping, or not grammatically and semantically parallel.

Do not reject a fair trivia clue merely because a knowledgeable player can infer the answer. The question should provide enough context to be answerable; reject only when the construction itself gives the answer away or makes the choices unfair.

When rejecting, return one or more short, specific instructions that a generator can use to rewrite the candidate. When approving, return no rejection reasons.

Return only structured JSON matching the requested schema.
