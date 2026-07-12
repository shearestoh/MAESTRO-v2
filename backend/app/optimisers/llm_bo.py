"""
MAESTRO-Oracle LLM Bayesian Optimiser.

Uses MAESTRO's structured lab context (instruments, literature, history, safety)
to construct domain-enriched elicitation prompts for an LLM surrogate, following
the POINTWISE protocol from Lei & Cooper (2026) "Elicitation Matters".

Key design decisions:
- POINTWISE querying (one candidate per call) rather than JOINT, because the
  paper shows POINTWISE better preserves ambiguity-sensitive uncertainty and
  observation faithfulness — especially important in sparse early-stage campaigns.
- Sampling-based uncertainty (n repeated calls at temperature > 0) rather than
  token-level NLL, because the GitHub Models API does not expose logprobs.
- Composite acquisition: UCB(LLM mean, sampling variance) weighted by physical
  feasibility (instrument failure probability) from the adapter layer.
- Evidence is presented to the LLM sorted by recency (most recent last) to
  mitigate the order-sensitivity effect documented in the paper.
- An UNDERDETERMINED warning is injected when n_obs < 5, following the paper's
  finding that this improves uncertainty alignment for sparse regimes.
  NOTE: The paper also shows gpt-4o-mini becomes MORE diffuse (not better
  calibrated) under complex structural prompts. Monitor empirically.
"""
from __future__ import annotations

import re
import statistics
from typing import List, Optional, Tuple

import numpy as np

from app.optimisers.base import BaseOptimiser


class MAESTROLLMOptimiser(BaseOptimiser):
    name = "MAESTRO LLM-BO (Oracle)"
    description = (
        "LLM surrogate Bayesian optimisation enriched with MAESTRO's lab context. "
        "Uses POINTWISE querying with domain-structured prompts drawn from instruments, "
        "literature, and experimental history. Uncertainty estimated via repeated sampling. "
        "Acquisition combines UCB with physical feasibility weighting. "
        "Best suited for low-data regimes where domain knowledge is available in the Library."
    )

    def __init__(
        self,
        n_samples:          int   = 5,
        temperature:        float = 0.8,
        ucb_kappa:          float = 2.0,
        feasibility_weight: float = 0.3,
        n_candidates:       int   = 20,
    ):
        self._bounds:             List[Tuple[float, float]] = []
        self._param_names:        List[str]                 = []
        self._history_x:          List[List[float]]         = []
        self._history_y:          List[float]               = []
        self._n_samples           = n_samples
        self._temperature         = temperature
        self._ucb_kappa           = ucb_kappa
        self._feasibility_weight  = feasibility_weight
        self._n_candidates        = n_candidates
        self._session             = None
        self._synth_instrument:   str = ""
        self._objective_metric:   str = ""
        self._rng                 = np.random.default_rng(42)

    def initialise(
        self,
        bounds:             List[Tuple[float, float]],
        n_initial_points:   int = 5,
        random_state:       int = 42,
        session             = None,
        synth_instrument:   str = "",
        objective_metric:   str = "",
        param_names:        Optional[List[str]] = None,
    ) -> None:
        self._bounds           = bounds
        self._param_names      = param_names or [f"x{i}" for i in range(len(bounds))]
        self._session          = session
        self._synth_instrument = synth_instrument
        self._objective_metric = objective_metric
        self._rng              = np.random.default_rng(random_state)

    def _build_prompt(self, candidate: List[float]) -> str:
        """
        Construct a domain-enriched POINTWISE elicitation prompt.
        Draws on: instrument specs, literature passages, lab notes, history.
        """
        from app.core.tool_registry import TOOL_REGISTRY
        from app.core.lab_config import get_lab_settings

        settings = get_lab_settings()

        # ── Instrument context ────────────────────────────────────────────────
        inst = TOOL_REGISTRY.get_by_name(self._synth_instrument) if self._synth_instrument else None
        instrument_block = ""
        if inst:
            param_descs = "; ".join(
                f"{p.name} [{p.min}–{p.max} {p.unit}]: {p.description}"
                for p in inst.parameters
            )
            output_descs = "; ".join(
                f"{o.name} ({o.unit}): {o.description}"
                for o in inst.outputs
            )
            fail_prob = inst.failure_modes[0].probability if inst.failure_modes else 0.0
            instrument_block = (
                f"\nINSTRUMENT: {inst.name}\n"
                f"  Parameters: {param_descs}\n"
                f"  Outputs: {output_descs}\n"
                f"  Typical failure rate: {fail_prob:.0%}"
            )

        # ── Literature prior ──────────────────────────────────────────────────
        literature_block = ""
        if self._session and self._session.active_document_id:
            from app.core.documents import DOCUMENTS, retrieve_relevant_passages
            if self._session.active_document_id in DOCUMENTS:
                try:
                    passages = retrieve_relevant_passages(
                        self._session.active_document_id,
                        query=f"{self._objective_metric} {' '.join(self._param_names)}",
                        top_k=2,
                        max_chars=400,
                    )
                    if passages:
                        literature_block = (
                            "\nLITERATURE PRIOR (treat as domain knowledge, not ground truth):\n"
                            + "\n".join(passages[:2])
                        )
                except Exception:
                    pass

        # ── Lab context extension ─────────────────────────────────────────────
        lab_block = ""
        if settings.system_prompt_extension.strip():
            lab_block = f"\nLAB NOTES:\n{settings.system_prompt_extension.strip()[:300]}"

        # ── Historical observations (sorted oldest→newest for sequential updating) ──
        obs_lines: list[str] = []
        for i, (x, y) in enumerate(zip(self._history_x, self._history_y)):
            param_str = ", ".join(
                f"{name}={val:.4f}"
                for name, val in zip(self._param_names, x)
            )
            obs_lines.append(f"  [{i+1}] {param_str} → {self._objective_metric} = {y:.4f}")

        if obs_lines:
            obs_block = "OBSERVATIONS (from this lab's experiments, oldest first):\n" + "\n".join(obs_lines)
        else:
            obs_block = "OBSERVATIONS: none yet — this is the initial exploration phase."

        # ── Underdetermination warning for sparse regimes ─────────────────────
        # Per Lei & Cooper (2026): improves uncertainty alignment when n_obs < 5.
        # Note: may increase diffuseness for gpt-4o-mini — monitor empirically.
        underdet_block = ""
        if len(self._history_x) < 5:
            underdet_block = (
                "\nWARNING: The observation set is sparse. "
                "Many parameter combinations remain consistent with the data. "
                "Reflect this uncertainty — do not overfit to few points."
            )

        # ── Candidate ─────────────────────────────────────────────────────────
        candidate_str = ", ".join(
            f"{name}={val:.4f}"
            for name, val in zip(self._param_names, candidate)
        )

        return (
            f"You are a scientific surrogate model for a materials science laboratory.\n"
            f"Predict the {self._objective_metric} for a candidate experimental configuration.\n"
            f"Output ONLY a single numeric value. No explanation, no units, no extra text.\n"
            f"{instrument_block}"
            f"{literature_block}"
            f"{lab_block}\n\n"
            f"{obs_block}"
            f"{underdet_block}\n\n"
            f"CANDIDATE: {candidate_str}\n"
            f"Predicted {self._objective_metric} ="
        )

    def _query_pointwise(self, candidate: List[float]) -> Tuple[float, float]:
        """
        POINTWISE: query the LLM n_samples times independently.
        Returns (mean_prediction, sampling_variance).
        Sampling variance serves as the epistemic uncertainty proxy
        (replaces token NLL which is unavailable on the GitHub Models API).
        """
        from app.core.config import GITHUB_TOKEN, MODEL_NAME
        from openai import OpenAI

        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=GITHUB_TOKEN,
        )
        prompt      = self._build_prompt(candidate)
        predictions: list[float] = []

        for _ in range(self._n_samples):
            try:
                resp = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=20,
                    temperature=self._temperature,
                )
                text  = (resp.choices[0].message.content or "").strip()
                match = re.search(r"-?\d+\.?\d*", text)
                if match:
                    predictions.append(float(match.group()))
            except Exception:
                pass

        if not predictions:
            if self._history_y:
                return float(np.mean(self._history_y)), float(np.std(self._history_y) + 1e-6)
            return 0.0, 1.0

        mean = statistics.mean(predictions)
        var  = statistics.variance(predictions) if len(predictions) > 1 else 1.0
        return mean, var

    def _feasibility(self, candidate: List[float]) -> float:
        """
        Physical feasibility score in [0, 1].
        Uses the instrument adapter's failure_probability function if available.
        1.0 = fully feasible, 0.0 = certain failure.
        """
        from app.core.tools import _instrument_failure_probability
        if not self._synth_instrument:
            return 1.0
        param_dict = dict(zip(self._param_names, candidate))
        return 1.0 - _instrument_failure_probability(self._synth_instrument, param_dict)

    def suggest(self) -> List[float]:
        """
        Score a random candidate pool with the LLM surrogate + UCB acquisition.
        Composite score = UCB(mean, variance) * feasibility_weight.
        """
        candidates = [
            [float(self._rng.uniform(lo, hi)) for lo, hi in self._bounds]
            for _ in range(self._n_candidates)
        ]

        if not self._history_x:
            return candidates[0]

        best_score     = -np.inf
        best_candidate = candidates[0]

        for candidate in candidates:
            mean, var      = self._query_pointwise(candidate)
            feasibility    = self._feasibility(candidate)
            ucb            = mean + self._ucb_kappa * np.sqrt(max(var, 0.0))
            score          = ucb * (1.0 - self._feasibility_weight * (1.0 - feasibility))
            if score > best_score:
                best_score     = score
                best_candidate = candidate

        return best_candidate

    def update(self, x: List[float], y: float) -> None:
        self._history_x.append(list(x))
        self._history_y.append(y)

    def best_so_far(self) -> Tuple[Optional[List[float]], Optional[float]]:
        if not self._history_y:
            return None, None
        best_idx = int(np.argmax(self._history_y))
        return self._history_x[best_idx], self._history_y[best_idx]