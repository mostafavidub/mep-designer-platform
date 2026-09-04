# Design-basis input control standard

Active platform release: `18.5.9`

- Questions whose engineering contract requires a scalar value must render as a numeric input, never as semantic system choices.
- The UI must display the required unit beside the field and the server must reject missing, zero, negative, or nonnumeric values.
- Presentation adapters must preserve the canonical question key; prompt-text inference must never replace an explicit numeric key.
- CAD aliases such as `gas_service_pressure` must map back to the canonical questionnaire key `gas_pressure` before recovery.
- Structured CAD failures must remain machine-readable internally while customer pages show a safe explanation.
- Each regression must include a negative rendering test and a late-authority recovery test.
