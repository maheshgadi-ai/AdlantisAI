"""The AdlantisAI Streamlit app. Start it with `adlantis app`, or `adlantis demo` without keys."""

from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from adlantis.config import DEFAULT_PROFILE, PROFILES, ConfigurationError, get_settings
from adlantis.interfaces.app_support import (
    assets_by_channel,
    claim_rows,
    downloads,
    example_text,
    gap_rows,
    ledger_rows,
    list_runs,
    missing_keys,
    parse_inputs,
    sample_campaign_dir,
    status_text,
    warning_rows,
)
from adlantis.orchestrator.kit_store import KitError, approve_kit, load_kit
from adlantis.orchestrator.run_log import RunEvent, utc_now
from adlantis.orchestrator.runner import (
    RunDependencies,
    RunFailed,
    RunRequest,
    estimate_run,
    start_run,
)
from adlantis.schemas.inputs import InputFileError

DEMO = os.environ.get("ADLANTIS_DEMO") == "1"
OUTPUTS = Path(os.environ.get("ADLANTIS_OUTPUTS", "outputs"))


def show_kit(run_dir: Path) -> None:
    """The kit viewer: strategy, assets, claims, ledger, gaps, downloads, and sign-off."""
    kit = load_kit(run_dir)
    st.header(f"{kit.brand_name}: {kit.product_name}")
    if kit.status == "approved":
        st.success(status_text(kit))
    else:
        st.warning(status_text(kit))
    cols = st.columns(4)
    cols[0].metric("Assets", len(kit.assets))
    cols[1].metric("Claims", len(kit.claims))
    cols[2].metric("Gaps", len(kit.gaps))
    cols[3].metric("Cost", f"${kit.cost.total_usd:.2f}")
    tabs = st.tabs(
        [
            "Strategy",
            "Assets",
            "Claims appendix",
            "Issue ledger",
            "Gaps and warnings",
            "Export",
            "Sign-off",
        ]
    )
    with tabs[0]:
        _strategy(kit)
    with tabs[1]:
        _assets(kit)
    with tabs[2]:
        st.caption("Every claim in the kit, its verdict, and the fact or source behind it.")
        st.dataframe(pd.DataFrame(claim_rows(kit)), hide_index=True, width="stretch")
    with tabs[3]:
        rows = ledger_rows(kit)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("No issues were raised.")
    with tabs[4]:
        _gaps(kit)
    with tabs[5]:
        for label, content, name, mime in downloads(kit, run_dir):
            st.download_button(f"Download {label}", content, file_name=name, mime=mime)
    with tabs[6]:
        _sign_off(kit, run_dir)


def _strategy(kit) -> None:
    if kit.strategy is None:
        st.write(kit.summary)
        return
    st.markdown(f"**Positioning.** {kit.strategy.positioning}")
    st.markdown(f"**Concept.** {kit.strategy.concept}")
    st.markdown("**Key messages**")
    for message in kit.strategy.key_messages:
        st.markdown(f"- {message.message} `{', '.join(message.references)}`")
    st.markdown("**Channel plans**")
    st.caption(kit.channel_plan_label)
    for plan in kit.strategy.channel_mix:
        st.markdown(f"- **{plan.channel}:** {plan.role} {plan.rationale}")


def _assets(kit) -> None:
    prompts = {prompt.asset_id: prompt for prompt in kit.image_prompts}
    for channel, items in assets_by_channel(kit).items():
        st.subheader(channel)
        for item in items:
            with st.container(border=True):
                st.caption(item.asset.asset_id)
                for name, text in item.asset.fields.items():
                    st.markdown(f"**{name}**")
                    st.text(text)
                for warning in item.warnings:
                    st.caption(f"Warning: {warning.message}")
                prompt = prompts.get(item.asset.asset_id)
                if prompt:
                    st.caption(f"Image prompt: {prompt.prompt}")


def _gaps(kit) -> None:
    gaps, warnings = gap_rows(kit), warning_rows(kit)
    st.markdown("**Removed from the kit**")
    if gaps:
        st.dataframe(pd.DataFrame(gaps), hide_index=True, width="stretch")
    else:
        st.info("Nothing was removed.")
    st.markdown("**Warnings**")
    if warnings:
        st.dataframe(pd.DataFrame(warnings), hide_index=True, width="stretch")
    else:
        st.info("No warnings.")


def _sign_off(kit, run_dir: Path) -> None:
    if kit.approval is not None:
        st.success(f"Approved by {kit.approval.approved_by}.")
        return
    if kit.mode == "baseline":
        st.info("Baseline kits are unverified and cannot be approved.")
        return
    if DEMO:
        st.info("Sign-off is not available in the demo.")
        return
    st.write("Approving records your name, the time, and a fingerprint of this exact kit.")
    name = st.text_input("Your name", key="approver")
    typed = st.text_input(f"Type {run_dir.name} to confirm", key="confirm_run")
    if st.button("Approve kit", disabled=not name.strip() or typed.strip() != run_dir.name):
        try:
            approve_kit(run_dir, name, utc_now())
        except KitError as exc:
            st.error(str(exc))
        else:
            st.success("Approved.")
            st.rerun()


def new_campaign() -> None:
    """The campaign form, with the cost estimate shown before anything is billed."""
    st.header("New campaign")
    settings = get_settings()
    examples = example_text()
    brand = st.text_area("brand.yaml", examples["brand"], height=220)
    facts = st.text_area("facts.yaml", examples["facts"], height=220)
    product = st.text_area("product.yaml", examples["product"], height=160)
    cols = st.columns(3)
    profile = cols[0].selectbox(
        "Profile", list(PROFILES), index=list(PROFILES).index(DEFAULT_PROFILE)
    )
    max_cost = cols[1].number_input("Hard cap (USD)", min_value=0.05, value=1.0, step=0.25)
    baseline = cols[2].toggle("Single-prompt baseline")
    try:
        inputs = parse_inputs(brand, facts, product)
        missing = missing_keys(settings, profile, baseline)
    except (InputFileError, ConfigurationError) as exc:
        st.error(str(exc))
        return
    request = RunRequest(
        inputs=inputs,
        max_cost_usd=max_cost,
        profile=profile,
        baseline=baseline,
        outputs_dir=OUTPUTS,
    )
    estimate = estimate_run(request, settings)
    st.info(
        f"Estimated cost: about ${estimate.typical_usd:.2f}, at most "
        f"${estimate.worst_case_usd:.2f}. No call can pass the ${max_cost:.2f} cap."
    )
    if missing:
        st.warning(f"Set {', '.join(missing)} to run a campaign.")
    accepted = st.checkbox(f"I accept charges of up to ${max_cost:.2f}")
    if st.button("Start campaign", disabled=bool(missing) or not accepted):
        _run(request, settings)


def _run(request: RunRequest, settings) -> None:
    events: queue.Queue[RunEvent] = queue.Queue()
    outcome: dict = {}

    def work() -> None:
        try:
            outcome["output"] = start_run(request, settings, RunDependencies(on_event=events.put))
        except RunFailed as exc:
            outcome["error"] = str(exc)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    with st.status("Running the campaign", expanded=True) as status:
        while worker.is_alive() or not events.empty():
            while not events.empty():
                event = events.get()
                detail = f": {event.detail}" if event.detail else ""
                status.write(f"`{event.at:%H:%M:%S}` {event.stage} {event.status}{detail}")
            time.sleep(0.5)
        failed = "error" in outcome
        status.update(
            label="Run failed" if failed else "Run finished",
            state="error" if failed else "complete",
        )
    if "error" in outcome:
        st.error(outcome["error"])
    else:
        st.session_state["run_dir"] = str(outcome["output"].run_dir)
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="AdlantisAI", layout="wide")
    st.title("AdlantisAI")
    st.caption(
        "Marketing campaigns where every claim is traceable to an approved fact or a source."
    )
    if DEMO:
        st.sidebar.info("Demo: an approved sample campaign. No API keys are needed.")
        show_kit(sample_campaign_dir())
        return
    choice = st.sidebar.radio("View", ["Saved kits", "New campaign"])
    if choice == "New campaign":
        new_campaign()
        return
    runs = list_runs(OUTPUTS)
    options = {path.name: path for path in runs} | {"Sample campaign": sample_campaign_dir()}
    default = st.session_state.get("run_dir")
    names = list(options)
    index = names.index(Path(default).name) if default and Path(default).name in names else 0
    selected = st.sidebar.selectbox("Kit", names, index=index)
    show_kit(options[selected])


main()
