# V2 Refactor Plan

## Goal

Refactor `openlrc/gui_qt/main_window_v2.py` into smaller, focused component files without changing the current V2 visual structure or interaction behavior.

The refactor should preserve:

- the current Apple-style dark visual direction
- the left navigation drawer
- the central workspace
- the right settings drawer
- the fluid accordion interaction
- the drawer open/close animation behavior

## Why Refactor

`main_window_v2.py` currently mixes:

- style definitions
- custom accordion widget logic
- left sidebar construction
- main workspace construction
- right drawer construction
- drawer animation state
- top bar interaction

This is acceptable for a prototype, but it is the wrong shape for continued feature work.
If business logic is added directly into this file, it will become difficult to reason about layout regressions, interaction state, and future widget reuse.

## Target File Structure

```text
openlrc/
  gui_qt/
    main_window_v2.py
    styles/
      __init__.py
      apple_dark.py
    widgets/
      __init__.py
      fluid_card.py
      v2_sidebar.py
      v2_workspace.py
      v2_settings_drawer.py
```

## Component Responsibilities

### `styles/apple_dark.py`

Owns:

- the V2 stylesheet string

Does not own:

- widget construction
- runtime state

### `widgets/fluid_card.py`

Owns:

- `FluidAccordionCard`
- accordion expansion animation
- content-height and layout refresh behavior

Does not own:

- page-level state
- drawer logic

### `widgets/v2_sidebar.py`

Owns:

- left icon navigation
- button selection behavior

Does not own:

- drawer width animation

### `widgets/v2_workspace.py`

Owns:

- top bar
- workspace title
- dropzone
- task table
- console

Does not own:

- right drawer state
- left drawer state

### `widgets/v2_settings_drawer.py`

Owns:

- right drawer content
- the three accordion cards
- local widget creation for form controls

Does not own:

- wrapper width animation
- application-level orchestration

### `main_window_v2.py`

Owns:

- composition of the three major regions
- left and right drawer wrappers
- left/right drawer width animation
- top-level window behavior

Does not own:

- stylesheet definition
- accordion implementation details
- detailed child layout construction

## Execution Steps

1. Extract the stylesheet into `styles/apple_dark.py`.
2. Extract `FluidAccordionCard` into `widgets/fluid_card.py`.
3. Extract the left sidebar into `widgets/v2_sidebar.py`.
4. Extract the central workspace into `widgets/v2_workspace.py`.
5. Extract the right settings drawer into `widgets/v2_settings_drawer.py`.
6. Reduce `main_window_v2.py` to composition and drawer animation only.
7. Run syntax validation.
8. Run offscreen window initialization and verify the V2 window still loads.

## Guardrails

- Do not change current V2 sizing defaults unless required for the refactor to preserve current behavior.
- Do not mix business logic into the newly extracted display components.
- Keep ASCII-only code unless the existing file already uses non-ASCII and it improves readability.
- Preserve the current V2 startup entry after refactor.

## Done Criteria

The refactor is complete when:

- the V2 UI is split into independent files by function
- `main_window_v2.py` becomes substantially smaller
- V2 still starts from the desktop entry
- accordion expansion and drawer toggling still work
- no new overlap or clipping regressions are introduced
