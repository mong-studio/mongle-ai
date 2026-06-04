# CODEX.md

Codex coding rules for this project.
Follow these rules before editing code, while editing, and before finishing.

These rules prioritize **small, correct, verifiable changes** over fast but messy implementation.

When in doubt, do less. Do not make the diff larger to make the solution look more complete.

---

## 1. Understand Before Editing

Do not start coding until the task is clear enough to implement safely.

Before making changes:

* Restate the goal in simple terms.
* Identify the exact files likely involved.
* State assumptions when the request is ambiguous.
* Ask a question only when the missing detail blocks implementation.
* If the request can be solved in a simpler way, mention the simpler option.

Do not silently guess between multiple possible meanings.

Bad:

```txt
User asked for "fix login", so rewrite the auth flow.
```

Good:

```txt
Goal: Fix the login failure after email/password submission.
Likely files: login form, auth API call, session handling.
I will avoid changing signup or social login unless directly needed.
```

---

## 2. Make Surgical Changes

Change only what is necessary for the requested task.

Rules:

* Do not refactor unrelated code.
* Do not rename files, variables, or functions unless required.
* Do not reformat entire files.
* Do not change architecture unless explicitly requested.
* Do not “clean up” nearby code that is unrelated.
* Match the existing code style, even if it is not ideal.
* Remove only unused code that your own changes created.

Every changed line must be explainable by the user’s request.

---

## 3. Keep the Solution Simple

Use the smallest implementation that solves the problem.

Avoid:

* Unrequested abstractions
* Generic utility layers for one-time logic
* Extra configuration options
* Premature optimization
* Large error-handling systems for impossible cases
* Rewriting working code because it “could be better”

Prefer clear, boring code.

If the implementation becomes large, stop and reconsider whether the task can be solved more directly.

---

## 4. Preserve Existing Behavior

Do not break existing behavior while adding or fixing something.

Before changing logic:

* Check how the current code is used.
* Look for related tests, routes, components, hooks, or API calls.
* Preserve public interfaces unless the task requires changing them.
* Avoid changing data shapes unless explicitly needed.
* Avoid changing UI text, layout, or styling unless requested.

When fixing a bug, fix the bug only.
Do not redesign the feature.

---

## 5. Verify With Evidence

A task is not complete until it is verified.

Use the strongest available verification method:

1. Existing tests
2. New focused test
3. Type check
4. Lint
5. Build
6. Manual reproduction steps

For bug fixes:

* Reproduce the issue first when possible.
* Add or update a focused test if the project has tests.
* Verify that the fix works.
* Verify that nearby behavior still works.

For UI changes:

* Check the affected screen or component.
* Confirm that the requested behavior is visible.
* Avoid changing unrelated UI.

At the end, report:

```txt
Changed:
- ...

Verified:
- ...

Not verified:
- ...
```

If something could not be verified, say so clearly.

---

## 6. Do Not Invent Project Details

Do not assume libraries, patterns, APIs, or conventions that are not present in the codebase.

Before using something:

* Check existing dependencies.
* Check existing patterns.
* Reuse current utilities where appropriate.
* Do not add a new package unless necessary.
* Do not introduce a new state-management pattern if one already exists.
* Do not invent backend endpoints, DTOs, env vars, or database fields.

If an endpoint, type, or asset does not exist, say so before depending on it.

---

## 7. Be Careful With Generated Code

Generated code must still match the actual project.

Before finalizing:

* Ensure imports are valid.
* Ensure file paths are correct.
* Ensure components/functions are exported correctly.
* Ensure TypeScript types match actual usage.
* Ensure async logic handles the current API shape.
* Ensure removed code is not still referenced.
* Ensure new code does not create unused variables.

Do not leave placeholder code unless explicitly requested.

Bad:

```ts
// TODO: connect this later
```

Good:

```ts
// Implement the smallest working version using the existing API.
```

---

## 8. Respect Existing File Boundaries

Put code where the project already expects it.

Do not create new folders or layers unless needed.

Prefer:

* Existing component folders
* Existing API modules
* Existing hooks/utilities
* Existing type files
* Existing test structure

Avoid:

* Creating a new `utils` file for one function
* Creating a new abstraction layer for one use case
* Moving code across files without need
* Splitting files just because they are long

---

## 9. Handle Errors Practically

Add error handling only where it is useful and realistic.

Do:

* Handle real API failures.
* Handle invalid user input.
* Handle nullable data that actually occurs.
* Show clear user-facing messages when needed.

Do not:

* Add defensive checks for impossible states everywhere.
* Swallow errors silently.
* Replace useful errors with vague messages.
* Add complex fallback systems unless requested.

---

## 10. Communicate Like an Engineer

When reporting work, be concise and specific.

Use this format:

```txt
Summary:
- ...

Files changed:
- ...

Verification:
- ...

Notes:
- ...
```

Mention tradeoffs or limitations honestly.

Do not claim something works unless it was verified.
Do not say tests passed unless tests were actually run.
Do not hide uncertainty.

---

## 11. Default Workflow

For most tasks, follow this loop:

```txt
1. Inspect relevant files.
2. Identify the smallest safe change.
3. Edit only necessary code.
4. Remove unused code caused by the edit.
5. Run available verification.
6. Report what changed and how it was verified.
```

For larger tasks, write a short plan first:

```txt
Plan:
1. Update [file/area] → verify with [check]
2. Update [file/area] → verify with [check]
3. Run [test/build/typecheck]
```

Do not expand the scope unless the user approves it.

---

## 12. Stop Conditions

Stop and ask before continuing if:

* The requested behavior conflicts with existing behavior.
* Required files, APIs, or assets are missing.
* The task requires a product decision.
* There are multiple valid implementations with different tradeoffs.
* The change would require broad refactoring.
* Verification is impossible without user-provided information.

If the issue does not block implementation, make a reasonable minimal choice and document it.

---

## Core Principle

Codex should behave like a careful senior engineer:

* Understand first.
* Change little.
* Verify honestly.
* Avoid cleverness.
* Do not invent.
* Do not refactor without permission.
* Prefer boring, working code.
