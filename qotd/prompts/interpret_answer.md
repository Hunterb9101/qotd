# Interpret a QOTD Answer

Interpret one Player email reply to a multiple-choice Question of the Day. Players may answer with a label, the wording of an option, an explanation, uncertainty, conversation, or a joke.

## Question and answer pairs

Question: {{ question.prompt }}

- A: {{ question.options.A }}
- B: {{ question.options.B }}
- C: {{ question.options.C }}
- D: {{ question.options.D }}

## Player reply

{{ reply_text }}

## Requirements

- Return A, B, C, or D whenever exactly one intended choice is discernible from the reply.
- Map clear answer wording to its corresponding option even when the Player does not include its letter.
- Treat joking, explanatory, hedged, uncertain, or conversational phrasing as tone, not ambiguity, when it still communicates one choice. For example, "Probably Jupiter, unless my science teacher lied" selects the Jupiter option.
- Return `UNKNOWN` only when there is no selection, materially conflicting selections, or a loophole attempt makes the intended answer indeterminate.
- A blank reply, "no idea," two incompatible final answers, or "give me credit for whichever is right" is `UNKNOWN`.
- Do not decide whether the selected option is correct. Only identify the Player's intended choice.
- Use the provided prompt and answer options as the only valid option set.
- Set `needs_review` to `false` for a discernible A/B/C/D selection.
- Set `needs_review` to `true` whenever the option is `UNKNOWN`.

## Output

Return only structured JSON matching the requested schema. Do not include markdown, commentary, or extra keys.
