---
trigger: always_on
---

## Table Formatting (CRITICAL for Dark Theme)

To ensure readability on dark themes, you **MUST wrap ALL textual content** within **EVERY table cell** using backticks (inline code formatting).

### Rules:
1. **Headers**: Wrap header text in backticks.
2. **Cells**: Wrap all cell content in backticks.
3. **No Exceptions**: Even long text, numerical values, or descriptions must be wrapped.
4. **Precedence**: This overrides standard markdown styling for tables.

> [!IMPORTANT]
> Failure to wrap table text in backticks results in poor contrast and unreadable text. **Always verify your table output follows this pattern.**

### Example:

| `Header 1` | `Header 2` | `Description`                                                               |
| :--------- | :--------- | :-------------------------------------------------------------------------- |
| `Cell 1`   | `Cell 2`   | `This is a longer description that is wrapped in backticks for visibility.` |
| `Item A`   | `123`      | `Values and text alike must be wrapped.`                                    |