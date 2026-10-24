"""Model discovery and per-run configuration.

Run from this directory:

    python model_discovery.py

Uses only the shipped API: Ranger.models() (static, no agent run),
with_config(), and per-call overrides on command methods.
"""

import ranger


def main() -> None:
    # discovery — lists what `opencode models` knows, no agent involved
    print("all models:", len(ranger.Ranger.models()))
    print("claude models:", ranger.Ranger.models(match="claude"))

    # configured copies — keep a slow Smart one and a fast Cheap one side by side
    smart = ranger.Ranger(model="openrouter/anthropic/claude-sonnet-4.5")
    cheap = smart.with_config(model="openrouter/google/gemini-2.5-flash", agent="general")
    print("smart:", smart.model, "/ cheap:", cheap.model)

    # per-call overrides — longer timeout and a session title for one run only
    answer = cheap.ask("say OK", title="config demo", timeout=120)
    print("cheap agent said:", answer)

    # the configured copies are independent; 'smart' was never touched
    print("smart still:", smart.model)


if __name__ == "__main__":
    main()
